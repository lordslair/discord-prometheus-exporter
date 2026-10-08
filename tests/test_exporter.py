# -*- coding: utf8 -*-

import asyncio
import urllib.error
import urllib.request

import discord
import pytest

from loguru import logger
from prometheus_client import REGISTRY

import exporter
from conftest import FakeChannel, FakeEvent, FakeGuild, FakeMember, sample, unique
from models.persistent_counter import PersistentCounter
from variables import env_vars


#
# Polling updates
#

def test_update_ping(fake_client):
    fake_client.latency = 0.123
    exporter.update_ping()
    assert sample('discord_latency') == 0.123


@pytest.mark.parametrize('latency', [float('nan'), float('inf')])
def test_update_ping_skips_unknown_latency(fake_client, latency):
    fake_client.latency = 0.042
    exporter.update_ping()

    # Not connected yet (inf), or disconnected (nan)
    fake_client.latency = latency
    exporter.update_ping()

    assert sample('discord_latency') == 0.042


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


# Each update, and the gauges it exports per guild
GUILD_UPDATES = [
    (exporter.update_registered, ['discord_members_registered', 'discord_bots_registered']),
    (exporter.update_online, ['discord_members_online', 'discord_bots_online']),
    (exporter.update_boost, ['discord_boosts']),
    (exporter.update_voice, [
        'discord_voice_members', 'discord_event_voice_members',
        'discord_voice_unique_members', 'discord_event_voice_unique_members',
        ]),
]


def exported(metrics, guild):
    """Whether any of these gauges has a series for this guild (other labels aside)."""
    name = guild if isinstance(guild, str) else guild.name
    return any(
        sample.labels.get('guild') == name
        for metric in REGISTRY.collect() if metric.name in metrics
        for sample in metric.samples
        )


@pytest.mark.parametrize('update, metrics', GUILD_UPDATES)
def test_joined_guild_is_exported(fake_client, update, metrics):
    first = FakeGuild([FakeMember()])
    fake_client.guilds = [first]
    update()

    joined = FakeGuild([FakeMember(), FakeMember(bot=True)])
    fake_client.guilds = [first, joined]
    update()

    assert exported(metrics, first)
    assert exported(metrics, joined)


@pytest.mark.parametrize('update, metrics', GUILD_UPDATES)
def test_left_guild_is_removed(fake_client, update, metrics):
    staying, leaving = FakeGuild([FakeMember()]), FakeGuild([FakeMember()])
    fake_client.guilds = [staying, leaving]
    update()

    fake_client.guilds = [staying]
    update()

    assert exported(metrics, staying)
    assert not exported(metrics, leaving)


@pytest.mark.parametrize('update, metrics', GUILD_UPDATES)
def test_renamed_guild_keeps_only_its_new_name(fake_client, update, metrics):
    guild = FakeGuild([FakeMember()])
    fake_client.guilds = [guild]
    update()
    old_name = guild.name

    guild.name = unique('renamed')
    update()

    assert exported(metrics, guild)
    assert not exported(metrics, old_name)


@pytest.mark.parametrize('update, metrics', GUILD_UPDATES)
def test_nothing_removed_until_ready(fake_client, update, metrics):
    guild = FakeGuild([FakeMember()])
    fake_client.guilds = [guild]
    update()

    # Reconnecting: guild list not loaded yet
    fake_client.ready = False
    fake_client.guilds = []
    update()

    assert exported(metrics, guild)


def test_updates_without_guilds(fake_client):
    # Before the client is ready, there are no guilds yet
    exporter.update_registered()
    exporter.update_online()
    exporter.update_boost()
    exporter.update_voice()


#
# Voice
#

class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def time(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    """Control the time update_voice sees, starting with no previous update."""
    clock = FakeClock()
    monkeypatch.setattr(exporter, 'time', clock)
    monkeypatch.setattr(exporter, 'voice_last_update', None)
    return clock


GENERAL, GAMING = FakeChannel(), FakeChannel()


def voice_seconds(guild):
    return sample('discord_voice_seconds_total', guild=guild.name)


def test_update_voice_members(fake_client, clock):
    afk = FakeChannel()
    guild = FakeGuild([
        FakeMember(voice=GENERAL),
        FakeMember(voice=GENERAL),
        FakeMember(voice=GAMING),
        FakeMember(),
        FakeMember(voice=afk),
        FakeMember(bot=True, voice=GENERAL),
    ], afk_channel=afk)
    fake_client.guilds = [guild]

    exporter.update_voice()

    # Any voice channel but the AFK one, bots excluded
    assert sample('discord_voice_members', guild=guild.name) == 3


def test_update_voice_first_update_counts_no_time(fake_client, clock):
    guild = FakeGuild([FakeMember(voice=GENERAL)])
    fake_client.guilds = [guild]

    exporter.update_voice()

    # Exported from the start, even before any time is counted
    assert REGISTRY.get_sample_value(
        'discord_voice_seconds_total', {'guild': guild.name}) == 0


def test_update_voice_counts_time_per_member(fake_client, clock):
    guild = FakeGuild([
        FakeMember(voice=GENERAL),
        FakeMember(voice=GENERAL),
        FakeMember(bot=True, voice=GENERAL),
    ])
    fake_client.guilds = [guild]
    exporter.update_voice()

    clock.now += 10
    exporter.update_voice()

    assert voice_seconds(guild) == 20


def test_update_voice_counts_actual_elapsed_time(fake_client, clock):
    guild = FakeGuild([FakeMember(voice=GENERAL)])
    fake_client.guilds = [guild]
    exporter.update_voice()

    # A late update counts the time since the previous one
    clock.now += 12.5
    exporter.update_voice()
    clock.now += 7.5
    exporter.update_voice()

    assert voice_seconds(guild) == 20


def test_update_voice_counts_members_in_voice_at_each_update(fake_client, clock):
    member = FakeMember()
    guild = FakeGuild([member, FakeMember(voice=GENERAL)])
    fake_client.guilds = [guild]
    exporter.update_voice()

    # Joins between two updates: counted since the previous one
    member.voice = FakeMember(voice=GENERAL).voice
    clock.now += 10
    exporter.update_voice()

    # Leaves: not counted anymore
    member.voice = None
    clock.now += 10
    exporter.update_voice()

    assert voice_seconds(guild) == 2 * 10 + 1 * 10
    assert sample('discord_voice_members', guild=guild.name) == 1


def test_update_voice_counts_each_guild_separately(fake_client, clock):
    first = FakeGuild([FakeMember(voice=GENERAL)])
    second = FakeGuild([FakeMember(voice=GENERAL), FakeMember(voice=GENERAL)])
    fake_client.guilds = [first, second]
    exporter.update_voice()

    clock.now += 10
    exporter.update_voice()

    assert voice_seconds(first) == 10
    assert voice_seconds(second) == 20


def test_update_voice_skips_disconnections(fake_client, clock):
    guild = FakeGuild([FakeMember(voice=GENERAL)])
    fake_client.guilds = [guild]
    exporter.update_voice()

    # Reconnecting for a while: unknown voice states, nothing counted
    fake_client.ready = False
    clock.now += 10
    exporter.update_voice()
    clock.now += 300
    fake_client.ready = True
    exporter.update_voice()

    # Counting again from the first update once ready
    clock.now += 10
    exporter.update_voice()

    assert voice_seconds(guild) == 10


def test_update_voice_keeps_time_of_left_guild(fake_client, clock):
    staying = FakeGuild([FakeMember(voice=GENERAL)])
    leaving = FakeGuild([FakeMember(voice=GENERAL)])
    fake_client.guilds = [staying, leaving]
    exporter.update_voice()
    clock.now += 10
    exporter.update_voice()

    fake_client.guilds = [staying]
    clock.now += 10
    exporter.update_voice()

    # A Counter, kept like messages and reactions
    assert voice_seconds(leaving) == 10
    assert voice_seconds(staying) == 20


def event_seconds(guild):
    return sample('discord_event_voice_seconds_total', guild=guild.name)


def test_update_voice_event_members(fake_client, clock):
    stage, external = FakeChannel(), 'https://example.com/live'
    guild = FakeGuild([
        FakeMember(voice=stage),
        FakeMember(voice=stage),
        FakeMember(voice=GENERAL),
        FakeMember(voice=GAMING),
        FakeMember(),
        FakeMember(bot=True, voice=stage),
    ], events=[
        FakeEvent(stage),
        FakeEvent(GAMING, status=discord.ScheduledEventStatus.scheduled),
        FakeEvent(external),
    ])
    fake_client.guilds = [guild]

    exporter.update_voice()

    # Only the channels of Events in progress, bots excluded
    assert sample('discord_event_voice_members', guild=guild.name) == 2
    # Members in an Event are in voice too
    assert sample('discord_voice_members', guild=guild.name) == 4


def test_update_voice_without_events(fake_client, clock):
    guild = FakeGuild([FakeMember(voice=GENERAL)])
    fake_client.guilds = [guild]
    exporter.update_voice()

    clock.now += 10
    exporter.update_voice()

    # Exported from the start, even without any Event
    assert sample('discord_event_voice_members', guild=guild.name) == 0
    assert REGISTRY.get_sample_value(
        'discord_event_voice_seconds_total', {'guild': guild.name}) == 0
    assert voice_seconds(guild) == 10


def test_update_voice_counts_event_time(fake_client, clock):
    stage = FakeChannel()
    event = FakeEvent(stage, status=discord.ScheduledEventStatus.scheduled)
    guild = FakeGuild([
        FakeMember(voice=stage),
        FakeMember(voice=stage),
        FakeMember(voice=GENERAL),
    ], events=[event])
    fake_client.guilds = [guild]
    exporter.update_voice()

    # Waiting in the channel before the Event starts: voice time only
    clock.now += 10
    exporter.update_voice()

    event.status = discord.ScheduledEventStatus.active
    clock.now += 20
    exporter.update_voice()

    event.status = discord.ScheduledEventStatus.completed
    clock.now += 10
    exporter.update_voice()

    assert event_seconds(guild) == 2 * 20
    assert voice_seconds(guild) == 3 * 40


def test_update_voice_counts_events_of_each_guild_separately(fake_client, clock):
    stage = FakeChannel()
    first = FakeGuild([FakeMember(voice=stage)], events=[FakeEvent(stage)])
    # Same channel, but no Event on this guild
    second = FakeGuild([FakeMember(voice=stage)])
    fake_client.guilds = [first, second]
    exporter.update_voice()

    clock.now += 10
    exporter.update_voice()

    assert event_seconds(first) == 10
    assert event_seconds(second) == 0


DAY = 86400


def unique_members(guild, window, metric='discord_voice_unique_members'):
    return sample(metric, guild=guild.name, window=window)


def test_update_voice_unique_members(fake_client, clock):
    alice, bob = FakeMember(voice=GENERAL), FakeMember(voice=GENERAL)
    guild = FakeGuild([alice, bob, FakeMember(), FakeMember(bot=True, voice=GENERAL)])
    fake_client.guilds = [guild]
    exporter.update_voice()

    # Bob leaves: still seen within the windows
    bob.voice = None
    clock.now += 10
    exporter.update_voice()

    # Alice again: counted once
    clock.now += 10
    exporter.update_voice()

    for window in ('1d', '7d', '30d'):
        assert unique_members(guild, window) == 2


def test_update_voice_unique_members_windows(fake_client, clock):
    alice, bob, carol = FakeMember(), FakeMember(), FakeMember()
    guild = FakeGuild([alice, bob, carol])
    fake_client.guilds = [guild]

    def call(member):
        """The member joins voice for one update, then leaves."""
        member.voice = FakeMember(voice=GENERAL).voice
        exporter.update_voice()
        member.voice = None

    call(alice)
    clock.now += 7 * DAY
    call(bob)
    clock.now += 2 * DAY
    call(carol)

    # Seen 9 days ago, 2 days ago, and now
    assert unique_members(guild, '1d') == 1
    assert unique_members(guild, '7d') == 2
    assert unique_members(guild, '30d') == 3


def test_update_voice_unique_members_expire(fake_client, clock):
    guild = FakeGuild([FakeMember(voice=GENERAL)])
    fake_client.guilds = [guild]
    exporter.update_voice()

    guild.members[0].voice = None
    clock.now += 30 * DAY + 1
    exporter.update_voice()

    assert unique_members(guild, '30d') == 0
    # Forgotten, not only out of the windows
    assert str(guild.id) not in exporter.METRICS['VOICE_UNIQUE_MEMBERS']._seen


def test_update_voice_event_unique_members(fake_client, clock):
    stage = FakeChannel()
    event = FakeEvent(stage)
    guild = FakeGuild([
        FakeMember(voice=stage),
        FakeMember(voice=stage),
        FakeMember(voice=GENERAL),
        FakeMember(bot=True, voice=stage),
    ], events=[event])
    fake_client.guilds = [guild]
    exporter.update_voice()

    # After the Event: members in its channel aren't in an Event anymore
    event.status = discord.ScheduledEventStatus.completed
    guild.members[2].voice = FakeMember(voice=stage).voice
    clock.now += 10
    exporter.update_voice()

    metric = 'discord_event_voice_unique_members'
    assert unique_members(guild, '1d', metric) == 2
    assert unique_members(guild, '1d') == 3


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

HEALTH_STATES = [
    # closed, ready, status, body
    (True, False, 503, 'DISCONNECTED'),
    (False, False, 503, 'NOT_READY'),
    (False, True, 200, 'OK'),
]


@pytest.mark.parametrize('closed, ready, status, body', HEALTH_STATES)
def test_health_status(fake_client, closed, ready, status, body):
    fake_client.closed = closed
    fake_client.ready = ready

    assert exporter.health_status() == (status, body)


@pytest.fixture
def health_url():
    """Start the real health server on a free port."""
    server = exporter.start_health_server(0)
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()
    server.server_close()


def get(url):
    """Status and body of a GET, errors included."""
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


@pytest.mark.parametrize('closed, ready, status, body', HEALTH_STATES)
def test_healthz_over_http(fake_client, health_url, closed, ready, status, body):
    fake_client.closed = closed
    fake_client.ready = ready

    assert get(f'{health_url}/healthz') == (status, body)


def test_healthz_ignores_query_string(fake_client, health_url):
    assert get(f'{health_url}/healthz?probe=liveness') == (200, 'OK')


def test_other_paths_are_not_found(fake_client, health_url):
    assert get(f'{health_url}/') == (404, 'NOT_FOUND')
    assert get(f'{health_url}/metrics') == (404, 'NOT_FOUND')


#
# Startup
#

@pytest.fixture
def no_servers(monkeypatch):
    """Keep main() from starting the save timer and the HTTP servers."""
    monkeypatch.setitem(env_vars, 'DISCORD_TOKEN', 'test-token')
    monkeypatch.setattr(exporter, 'periodic_save', lambda: None)
    monkeypatch.setattr(exporter, 'check_s3', lambda: True)
    monkeypatch.setattr(exporter, 'start_http_server', lambda port: None)
    monkeypatch.setattr(exporter, 'start_health_server', lambda port: None)


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


def test_main_exits_without_token(monkeypatch, fake_client, no_servers):
    monkeypatch.setitem(env_vars, 'DISCORD_TOKEN', None)
    started = []
    monkeypatch.setattr(exporter, 'periodic_save', lambda: started.append(1))
    fake_client.run = lambda token: started.append(1)

    with pytest.raises(SystemExit) as exc:
        exporter.main()

    assert exc.value.code == 1
    # Fails before starting anything
    assert started == []


def test_main_exits_when_s3_is_unavailable(monkeypatch, fake_client, no_servers):
    monkeypatch.setattr(exporter, 'check_s3', lambda: False)
    started = []
    monkeypatch.setattr(exporter, 'periodic_save', lambda: started.append(1))
    fake_client.run = lambda token: started.append(1)

    with pytest.raises(SystemExit) as exc:
        exporter.main()

    assert exc.value.code == 1
    # Never saves, so the stored state is left as it is
    assert started == []
