# -*- coding: utf8 -*-

from prometheus_client import Gauge
from loguru import logger

from models.persistent_counter import PersistentCounter
from models.unique_members import UniqueMembers

METRICS = {}

# Metrics definition
# Gauges
METRICS['PING'] = Gauge(
    'discord_latency',
    'The Discord WebSocket latency (heartbeat round trip), in seconds.',
    )
METRICS['MEMBERS_REGISTERED'] = Gauge(
    'discord_members_registered',
    'The number of members (bots excluded) on a Guild.',
    ['guild'],
    )
METRICS['MEMBERS_ONLINE'] = Gauge(
    'discord_members_online',
    'The number of online members on a Guild.',
    ['guild'],
    )
METRICS['BOTS_REGISTERED'] = Gauge(
    'discord_bots_registered',
    'The number of bots on a Guild.',
    ['guild'],
    )
METRICS['BOTS_ONLINE'] = Gauge(
    'discord_bots_online',
    'The number of online bots on a Guild.',
    ['guild'],
    )
METRICS['BOOSTS'] = Gauge(
    'discord_boosts',
    'The number of Server Boosts on a Guild.',
    ['guild'],
    )
METRICS['VOICE_MEMBERS'] = Gauge(
    'discord_voice_members',
    'The number of members (bots excluded) in a voice channel on a Guild.',
    ['guild'],
    )
METRICS['EVENT_VOICE_MEMBERS'] = Gauge(
    'discord_event_voice_members',
    'The number of members (bots excluded) in the channel of an Event in progress on a Guild.',
    ['guild'],
    )

# Counters
METRICS['MESSAGES'] = PersistentCounter(
    'discord_messages',
    'The number of messages sent on a Guild by a Member.',
    ['guild', 'member'],
    )
METRICS['REACTIONS'] = PersistentCounter(
    'discord_reactions',
    'The number of reactions added on a Guild by a Member.',
    ['guild', 'member'],
    )
METRICS['VOICE_SECONDS'] = PersistentCounter(
    'discord_voice_seconds',
    'The time spent in voice channels on a Guild by its members, in seconds.',
    ['guild'],
    )
METRICS['EVENT_VOICE_SECONDS'] = PersistentCounter(
    'discord_event_voice_seconds',
    'The time spent in the channels of Events in progress on a Guild by its members, in seconds.',
    ['guild'],
    )

# Unique members, over rolling windows
METRICS['VOICE_UNIQUE_MEMBERS'] = UniqueMembers(
    'discord_voice_unique_members',
    'The number of unique members (bots excluded) seen in a voice channel on a Guild.',
    )
METRICS['EVENT_VOICE_UNIQUE_MEMBERS'] = UniqueMembers(
    'discord_event_voice_unique_members',
    'The number of unique members (bots excluded) seen in the channel of an Event '
    'in progress on a Guild.',
    )

logger.info('[Exporter][✓] Metrics defined')
