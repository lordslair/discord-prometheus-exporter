# -*- coding: utf8 -*-

import json

import pytest

from loguru import logger
from prometheus_client import REGISTRY

from conftest import FakeGuild, FakeMember, sample, unique
from models.persistent_counter import PersistentCounter
from models.unique_members import UniqueMembers
from variables import env_vars

DAY = 86400


@pytest.fixture
def persist_file(monkeypatch, tmp_path):
    path = tmp_path / 'persist.json'
    monkeypatch.setitem(env_vars, 'PERSIST_FILE', str(path))
    return path


@pytest.fixture
def make_metric(monkeypatch):
    """Create UniqueMembers isolated from the exporter's own ones."""
    # Only the metrics created here get saved
    monkeypatch.setattr(PersistentCounter, '_registry', [])

    def make(name):
        return UniqueMembers(name, 'A test metric.')

    yield make

    for metric in PersistentCounter._registry:
        REGISTRY.unregister(metric.gauge)


def new_name():
    return unique('test_unique').replace('-', '_')


def restart(metric, make_metric):
    """Simulate an exporter restart: drop the metric, then create it again."""
    REGISTRY.unregister(metric.gauge)
    PersistentCounter._registry.remove(metric)
    return make_metric(metric._name)


def windows(name, guild):
    return {
        window: sample(name, guild=guild.name, window=window)
        for window in ('1d', '7d', '30d')
        }


def test_update_counts_each_member_once(make_metric):
    name = new_name()
    metric = make_metric(name)
    alice, bob = FakeMember(), FakeMember()
    guild = FakeGuild()

    metric.update(guild, [alice, bob], now=1000)
    metric.update(guild, [alice], now=1010)

    assert windows(name, guild) == {'1d': 2, '7d': 2, '30d': 2}


def test_update_counts_over_each_window(make_metric):
    name = new_name()
    metric = make_metric(name)
    guild = FakeGuild()
    now = 100 * DAY

    metric.update(guild, [FakeMember()], now=now - 20 * DAY)
    metric.update(guild, [FakeMember()], now=now - 3 * DAY)
    metric.update(guild, [FakeMember()], now=now)

    assert windows(name, guild) == {'1d': 1, '7d': 2, '30d': 3}


def test_update_counts_each_guild_separately(make_metric):
    name = new_name()
    metric = make_metric(name)
    first, second = FakeGuild(), FakeGuild()
    member = FakeMember()

    metric.update(first, [member], now=1000)
    metric.update(second, [member, FakeMember()], now=1000)

    assert windows(name, first)['1d'] == 1
    assert windows(name, second)['1d'] == 2


def test_update_without_members_exports_zero(make_metric):
    name = new_name()
    metric = make_metric(name)
    guild = FakeGuild()

    metric.update(guild, [], now=1000)

    assert REGISTRY.get_sample_value(name, {'guild': guild.name, 'window': '1d'}) == 0


def test_expire_forgets_members_not_seen_for_30_days(make_metric):
    metric = make_metric(new_name())
    old, recent = FakeMember(), FakeMember()
    guild = FakeGuild()
    now = 100 * DAY

    metric.update(guild, [old], now=now - 31 * DAY)
    metric.update(guild, [recent], now=now - 29 * DAY)
    metric.expire(now)

    assert metric._seen == {str(guild.id): {str(recent.id): now - 29 * DAY}}


def test_expire_forgets_empty_guilds(make_metric):
    metric = make_metric(new_name())
    metric.update(FakeGuild(), [FakeMember()], now=0)

    metric.expire(31 * DAY)

    assert metric._seen == {}


def test_members_survive_a_restart(persist_file, make_metric):
    name = new_name()
    metric = make_metric(name)
    guild = FakeGuild()
    metric.update(guild, [FakeMember(), FakeMember()], now=1000)

    PersistentCounter.save_all()
    metric = restart(metric, make_metric)
    metric.update(guild, [FakeMember()], now=1010)

    assert windows(name, guild)['1d'] == 3


def test_saved_with_the_counters(persist_file, make_metric):
    name = new_name()
    metric = make_metric(name)
    counter_name = new_name()
    counter = PersistentCounter(counter_name, 'A test counter.', ['guild'])
    guild, member = FakeGuild(), FakeMember()
    metric.update(guild, [member], now=1000)
    counter.labels(guild='guild').inc(3)

    PersistentCounter.save_all()

    state = json.loads(persist_file.read_text())
    assert state == {
        f'{name}:seen': {str(guild.id): {str(member.id): 1000}},
        f'{counter_name}_total:{json.dumps({"guild": "guild"})}': 3,
    }
    REGISTRY.unregister(counter.counter)
    PersistentCounter._registry.remove(counter)


def test_counter_ignores_entries_sharing_its_prefix(persist_file, make_metric):
    name = new_name()
    # Same prefix as the counter below, not a counter entry
    metric = make_metric(f'{name}_unique')
    metric.update(FakeGuild(), [FakeMember()], now=1000)
    PersistentCounter.save_all()

    errors = []
    handler = logger.add(errors.append, level='ERROR')
    try:
        counter = PersistentCounter(name, 'A test counter.', ['guild'])
    finally:
        logger.remove(handler)

    # Not mistaken for one of its entries
    assert errors == []
    assert REGISTRY.get_sample_value(f'{name}_total', {'guild': 'guild'}) is None
    REGISTRY.unregister(counter.counter)
    PersistentCounter._registry.remove(counter)


def test_nothing_saved_without_members(persist_file, make_metric):
    make_metric(new_name())

    PersistentCounter.save_all()

    assert not persist_file.exists()


def test_invalid_persist_file_is_ignored(persist_file, make_metric):
    persist_file.write_text('not json')
    name = new_name()

    # Starts empty instead of crashing the exporter
    metric = make_metric(name)
    guild = FakeGuild()
    metric.update(guild, [FakeMember()], now=1000)

    assert windows(name, guild)['1d'] == 1
