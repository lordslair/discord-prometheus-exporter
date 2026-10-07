# -*- coding: utf8 -*-

import asyncio

import discord
import pytest

from loguru import logger

import exporter
from conftest import FakeGuild, FakeMember, sample
from models.persistent_counter import PersistentCounter


#
# Polling updates
#

def test_update_ping(fake_client):
    fake_client.latency = 0.123
    exporter.update_ping()
    assert sample('discord_latency') == 0.123


def test_update_registered(fake_client):
    guild = FakeGuild([FakeMember(), FakeMember(), FakeMember(bot=True)])
    fake_client.guilds = [guild]

    exporter.update_registered()

    assert sample('discord_members_registered', guild=guild.name) == 2
    assert sample('discord_bots_registered', guild=guild.name) == 1


def test_update_registered_counts_each_guild_separately(fake_client):
    first = FakeGuild([FakeMember(), FakeMember(bot=True)])
    second = FakeGuild([FakeMember(), FakeMember(), FakeMember(bot=True)])
    fake_client.guilds = [first, second]

    exporter.update_registered()

    assert sample('discord_members_registered', guild=first.name) == 1
    assert sample('discord_bots_registered', guild=first.name) == 1
    assert sample('discord_members_registered', guild=second.name) == 2
    assert sample('discord_bots_registered', guild=second.name) == 1


def test_update_online(fake_client):
    guild = FakeGuild([
        FakeMember(status=discord.Status.online),
        FakeMember(status=discord.Status.idle),
        FakeMember(status=discord.Status.dnd),
        FakeMember(status=discord.Status.offline),
        FakeMember(bot=True, status=discord.Status.online),
        FakeMember(bot=True, status=discord.Status.offline),
    ])
    fake_client.guilds = [guild]

    exporter.update_online()

    # Anything but offline counts as online (idle, dnd, ...)
    assert sample('discord_members_online', guild=guild.name) == 3
    assert sample('discord_bots_online', guild=guild.name) == 1


def test_update_online_counts_each_guild_separately(fake_client):
    first = FakeGuild([FakeMember(), FakeMember(bot=True)])
    second = FakeGuild([FakeMember(), FakeMember()])
    fake_client.guilds = [first, second]

    exporter.update_online()

    assert sample('discord_members_online', guild=first.name) == 1
    assert sample('discord_bots_online', guild=first.name) == 1
    assert sample('discord_members_online', guild=second.name) == 2
    assert sample('discord_bots_online', guild=second.name) == 0


def test_update_boost(fake_client):
    guild = FakeGuild(boosts=7)
    fake_client.guilds = [guild]

    exporter.update_boost()

    assert sample('discord_boosts', guild=guild.name) == 7


def test_updates_without_guilds(fake_client):
    # Before the client is ready, there are no guilds yet
    exporter.update_registered()
    exporter.update_online()
    exporter.update_boost()


#
# Polling loop
#

def test_poll_runs_until_client_is_closed(fake_client):
    calls = []

    def update():
        calls.append(1)
        if len(calls) == 3:
            fake_client.closed = True

    asyncio.run(exporter.poll(update, 0))

    assert len(calls) == 3


def test_poll_survives_a_failing_update(fake_client):
    calls = []

    def update():
        calls.append(1)
        if len(calls) == 2:
            fake_client.closed = True
        raise RuntimeError('boom')

    asyncio.run(exporter.poll(update, 0))

    assert len(calls) == 2


#
# Discord events
#

def test_on_message_counts_members():
    guild = FakeGuild()
    author = FakeMember(guild=guild)
    message = type('Message', (), {'author': author, 'guild': guild})

    asyncio.run(exporter.on_message(message))
    asyncio.run(exporter.on_message(message))

    assert sample('discord_messages_total', guild=guild.name, member=author.name) == 2


def test_on_message_ignores_bots():
    guild = FakeGuild()
    author = FakeMember(bot=True, guild=guild)
    message = type('Message', (), {'author': author, 'guild': guild})

    asyncio.run(exporter.on_message(message))

    assert sample('discord_messages_total', guild=guild.name, member=author.name) == 0


def test_on_message_ignores_direct_messages():
    author = FakeMember()
    message = type('Message', (), {'author': author, 'guild': None})

    asyncio.run(exporter.on_message(message))

    assert sample('discord_messages_total', guild='None', member=author.name) == 0


def reaction(member):
    return type('RawReactionActionEvent', (), {'member': member})


def test_on_raw_reaction_add_counts_members():
    guild = FakeGuild()
    member = FakeMember(guild=guild)

    asyncio.run(exporter.on_raw_reaction_add(reaction(member)))
    asyncio.run(exporter.on_raw_reaction_add(reaction(member)))

    assert sample('discord_reactions_total', guild=guild.name, member=member.name) == 2


def test_on_raw_reaction_add_ignores_bots():
    guild = FakeGuild()
    member = FakeMember(bot=True, guild=guild)

    asyncio.run(exporter.on_raw_reaction_add(reaction(member)))

    assert sample('discord_reactions_total', guild=guild.name, member=member.name) == 0


def test_on_raw_reaction_add_ignores_direct_messages():
    errors = []
    handler = logger.add(errors.append, level='ERROR')
    try:
        # In direct messages, Discord sends no member
        asyncio.run(exporter.on_raw_reaction_add(reaction(None)))
    finally:
        logger.remove(handler)

    # Skipped, not failing (and logged) on the missing member
    assert errors == []


def test_old_reaction_event_is_gone():
    # Counting both would count every cached reaction twice
    assert not hasattr(exporter, 'on_reaction_add')


#
# Health check
#

@pytest.mark.parametrize('closed, ready, status, body', [
    (True, False, 503, b'DISCONNECTED'),
    (False, False, 503, b'NOT_READY'),
    (False, True, 200, b'OK'),
])
def test_healthz(fake_client, closed, ready, status, body):
    fake_client.closed = closed
    fake_client.ready = ready

    response = exporter.app.test_client().get('/healthz')

    assert response.status_code == status
    assert response.data == body


#
# Startup
#

@pytest.fixture
def no_servers(monkeypatch):
    """Keep main() from starting the save timer and the HTTP servers."""
    monkeypatch.setattr(exporter, 'periodic_save', lambda: None)
    monkeypatch.setattr(exporter, 'start_http_server', lambda port: None)
    monkeypatch.setattr(exporter, 'run_flask', lambda: None)


@pytest.fixture
def saves(monkeypatch):
    """Count the Counter persistence saves."""
    calls = []
    monkeypatch.setattr(PersistentCounter, 'save_all', lambda: calls.append(1))
    return calls


def test_main_exits_when_client_fails(fake_client, no_servers):
    def run(token):
        raise RuntimeError('Improper token has been passed.')
    fake_client.run = run

    # Non-zero, so the container gets restarted
    with pytest.raises(SystemExit) as exc:
        exporter.main()
    assert exc.value.code == 1


def test_main_returns_when_client_stops(fake_client, no_servers):
    # client.run() returns on a clean shutdown (SIGTERM): no error then
    assert exporter.main() is None


def test_main_saves_counters_on_shutdown(fake_client, no_servers, saves):
    exporter.main()

    assert len(saves) == 1


def test_main_saves_counters_when_client_fails(fake_client, no_servers, saves):
    def run(token):
        raise RuntimeError('Connection reset')
    fake_client.run = run

    with pytest.raises(SystemExit):
        exporter.main()

    assert len(saves) == 1
