# -*- coding: utf8 -*-

import pytest

from loguru import logger

from variables import default_persist_timer, env_vars, log_env_vars


@pytest.fixture
def logs():
    """Capture what loguru writes."""
    messages = []
    handler = logger.add(messages.append, level='DEBUG', format='{message}')
    yield messages
    logger.remove(handler)


def test_token_is_never_logged_in_full(monkeypatch, logs):
    token = 'MTA2NzQ1.GxYz12.abcdefghijklmnopqrstuvwxyz0123456789'
    monkeypatch.setitem(env_vars, 'DISCORD_TOKEN', token)

    log_env_vars()

    assert not any(token in message for message in logs)
    # Both ends only, to tell which token is set
    assert 'DISCORD_TOKEN: MTA2...6789\n' in logs


def test_short_token_is_fully_masked(monkeypatch, logs):
    monkeypatch.setitem(env_vars, 'DISCORD_TOKEN', 'short-secret')

    log_env_vars()

    assert not any('short' in message or 'cret' in message for message in logs)
    assert 'DISCORD_TOKEN: ********\n' in logs


def test_missing_token_is_still_reported(monkeypatch, logs):
    monkeypatch.setitem(env_vars, 'DISCORD_TOKEN', None)

    log_env_vars()

    assert 'DISCORD_TOKEN: None\n' in logs


def test_other_vars_are_logged(monkeypatch, logs):
    monkeypatch.setitem(env_vars, 'POLLING_INTERVAL', 10)

    log_env_vars()

    assert 'POLLING_INTERVAL: 10\n' in logs


@pytest.mark.parametrize('persist_file, timer', [
    (None, 60),
    ('/data/counters.json', 60),
    # Each save is a request
    ('s3://bucket/dpe/counters.json', 900),
])
def test_default_persist_timer(persist_file, timer):
    assert default_persist_timer(persist_file) == timer
