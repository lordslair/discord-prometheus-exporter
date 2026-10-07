# -*- coding: utf8 -*-

import json

import pytest

from prometheus_client import REGISTRY

from conftest import sample, unique
from models import persistent_counter
from models.persistent_counter import PersistentCounter, periodic_save
from variables import env_vars


@pytest.fixture
def persist_file(monkeypatch, tmp_path):
    path = tmp_path / 'persist.json'
    monkeypatch.setitem(env_vars, 'PERSIST_FILE', str(path))
    return path


@pytest.fixture
def make_counter(monkeypatch):
    """Create PersistentCounters isolated from the exporter's own ones."""
    # Only the counters created here get saved
    monkeypatch.setattr(PersistentCounter, '_registry', [])

    def make(name):
        return PersistentCounter(name, 'A test counter.', ['guild', 'member'])

    yield make

    for counter in PersistentCounter._registry:
        REGISTRY.unregister(counter.counter)


def restart(counter, make_counter):
    """Simulate an exporter restart: drop the counter, then create it again."""
    REGISTRY.unregister(counter.counter)
    PersistentCounter._registry.remove(counter)
    return make_counter(counter._name)


def test_counter_survives_a_restart(persist_file, make_counter):
    name = unique('test_counter').replace('-', '_')
    counter = make_counter(name)
    counter.labels(guild='guild', member='member').inc(3)

    PersistentCounter.save_all()
    restart(counter, make_counter)

    assert sample(f'{name}_total', guild='guild', member='member') == 3


def test_save_all_writes_every_label_set(persist_file, make_counter):
    name = unique('test_counter').replace('-', '_')
    counter = make_counter(name)
    counter.labels(guild='guild', member='alice').inc()
    counter.labels(guild='guild', member='bob').inc(2)

    PersistentCounter.save_all()

    state = json.loads(persist_file.read_text())
    assert state == {
        f'{name}_total:{json.dumps({"guild": "guild", "member": "alice"})}': 1,
        f'{name}_total:{json.dumps({"guild": "guild", "member": "bob"})}': 2,
    }


def test_save_all_skips_empty_state(persist_file, make_counter):
    make_counter(unique('test_counter').replace('-', '_'))

    PersistentCounter.save_all()

    assert not persist_file.exists()


def test_save_all_without_persist_file(monkeypatch, make_counter, tmp_path):
    monkeypatch.setitem(env_vars, 'PERSIST_FILE', None)
    counter = make_counter(unique('test_counter').replace('-', '_'))
    counter.labels(guild='guild', member='member').inc()

    PersistentCounter.save_all()

    assert list(tmp_path.iterdir()) == []


def test_invalid_persist_file_is_ignored(persist_file, make_counter):
    persist_file.write_text('not json')
    name = unique('test_counter').replace('-', '_')

    # Starts from zero instead of crashing the exporter
    counter = make_counter(name)
    counter.labels(guild='guild', member='member').inc()

    assert sample(f'{name}_total', guild='guild', member='member') == 1


def test_failed_save_keeps_the_previous_file(monkeypatch, persist_file, make_counter):
    persist_file.write_text('{"previous": 1}')
    counter = make_counter(unique('test_counter').replace('-', '_'))
    counter.labels(guild='guild', member='member').inc()

    # Dies halfway through writing, like a crash or a full disk would
    def broken_dump(state, f):
        f.write('{"trunc')
        raise OSError('No space left on device')
    monkeypatch.setattr(persistent_counter.json, 'dump', broken_dump)

    with pytest.raises(OSError):
        PersistentCounter.save_all()

    assert persist_file.read_text() == '{"previous": 1}'
    # No temporary file left behind
    assert [p.name for p in persist_file.parent.iterdir()] == ['persist.json']


def test_save_leaves_no_temporary_file(persist_file, make_counter):
    counter = make_counter(unique('test_counter').replace('-', '_'))
    counter.labels(guild='guild', member='member').inc()

    PersistentCounter.save_all()
    PersistentCounter.save_all()

    assert [p.name for p in persist_file.parent.iterdir()] == ['persist.json']


def test_periodic_save_keeps_going_after_a_failure(monkeypatch):
    timers = []

    class FakeTimer:
        def __init__(self, interval, function):
            timers.append(function)

        def start(self):
            pass

    def broken_save():
        raise OSError('No space left on device')

    monkeypatch.setattr(persistent_counter.threading, 'Timer', FakeTimer)
    monkeypatch.setattr(PersistentCounter, 'save_all', broken_save)

    periodic_save()

    # The next save is still scheduled
    assert timers == [periodic_save]
