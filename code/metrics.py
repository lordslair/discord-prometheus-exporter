# -*- coding: utf8 -*-

from prometheus_client import Gauge, Counter
from loguru import logger

METRICS = {}

# Metrics definition
# Gauges
METRICS['PING'] = Gauge(
    'discord_latency',
    'The time in ms that discord took to respond to a REST request.',
    )
METRICS['MEMBERS_REGISTERED'] = Gauge(
    'discord_members_registered',
    'The number of connected members on a Guild.',
    ['guild'],
    )
METRICS['MEMBERS_ONLINE'] = Gauge(
    'discord_members_online',
    'The number of online members on a Guild.',
    ['guild'],
    )
METRICS['BOTS_REGISTERED'] = Gauge(
    'discord_bots_registered',
    'The number of connected bots on a Guild.',
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

# Counters
METRICS['MESSAGES'] = Counter(
    'discord_messages',
    'The number of messages sent on a Guild by a Member.',
    ['guild', 'member'],
    )
METRICS['REACTIONS'] = Counter(
    'discord_reactions',
    'The number of messages sent on a Guild by a Member.',
    ['guild', 'member'],
    )

logger.info('[Exporter][✓] Metrics defined')
