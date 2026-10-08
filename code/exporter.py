#!/usr/bin/env python3
# -*- coding: utf8 -*-

import asyncio
import discord
import math
import sys
import threading
import time

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from prometheus_client import start_http_server
from loguru import logger

from variables import env_vars
from metrics import METRICS
from models.persistent_counter import PersistentCounter, check_s3, periodic_save

# ========== Health Check Setup ==========


# We'll use the 'client' variable defined below in the health endpoint
def health_status():
    """HTTP status and body for /healthz, from the Discord client's state."""
    if client.is_closed():
        return 503, 'DISCONNECTED'
    elif not client.is_ready():
        return 503, 'NOT_READY'
    else:
        return 200, 'OK'


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split('?')[0] == '/healthz':
            status, body = health_status()
        else:
            status, body = 404, 'NOT_FOUND'

        payload = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        # Probes call it every few seconds: trace only, not every request
        logger.trace(f'[Exporter] Health check: {format % args}')


def start_health_server(port):
    """Serve /healthz in a background thread, returns the server."""
    # Use a port different from the Prometheus exporter (default 8081 here)
    server = ThreadingHTTPServer(('0.0.0.0', port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
# ========================================


# Intents are needed since 2020 for Member and Messages infos
# Needs to be activated in bots preferences in discord portal
intents = discord.Intents.default()
intents.members = True
intents.presences = True
# Only creates the client: it connects in main(), with client.run()
client = discord.Client(intents=intents)


#
# Tasks definition
#

def update_ping():
    latency = client.latency
    # NaN while disconnected, infinite until the first heartbeat is answered:
    # keep the last real value instead of exporting those
    if math.isfinite(latency):
        METRICS['PING'].set(latency)


def prune_guilds(*keys):
    """
    Remove the series of guilds the bot is no longer in from these gauges.

    Covers a guild the bot left, and a renamed one (labels are guild names):
    otherwise their last values would stay exported forever.
    """
    # Until ready (startup, reconnection), the guild list is empty or partial:
    # pruning then would drop the series of guilds the bot is still in
    if not client.is_ready():
        return
    current = {str(guild) for guild in client.guilds}
    for key in keys:
        # All the labels of each series, to remove it (guild, and maybe others)
        stale = {
            tuple(sample.labels.values())
            for metric in METRICS[key].collect()
            for sample in metric.samples
            if sample.labels['guild'] not in current
            }
        for labels in stale:
            METRICS[key].remove(*labels)
            logger.debug(f'[Exporter] Removed {labels} from {key}')


def update_registered():
    for guild in client.guilds:
        members_registered = 0
        bots_registered = 0
        for member in guild.members:
            if member.bot is False:
                members_registered += 1
            else:
                bots_registered += 1
        METRICS['BOTS_REGISTERED'].labels(guild=guild).set(bots_registered)
        METRICS['MEMBERS_REGISTERED'].labels(guild=guild).set(members_registered)
    prune_guilds('BOTS_REGISTERED', 'MEMBERS_REGISTERED')


def update_online():
    for guild in client.guilds:
        members_online = 0
        bots_online = 0
        for member in guild.members:
            if member.status is discord.Status.offline:
                continue
            if member.bot is False:
                members_online += 1
            else:
                bots_online += 1
        METRICS['BOTS_ONLINE'].labels(guild=guild).set(bots_online)
        METRICS['MEMBERS_ONLINE'].labels(guild=guild).set(members_online)
    prune_guilds('BOTS_ONLINE', 'MEMBERS_ONLINE')


def update_boost():
    for guild in client.guilds:
        METRICS['BOOSTS'].labels(guild=guild).set(guild.premium_subscription_count)
    prune_guilds('BOOSTS')


# When update_voice last ran (monotonic clock), None to start counting afresh
voice_last_update = None


def in_voice(member):
    """Whether this member is in a call: any voice channel but the AFK one."""
    voice = member.voice
    if voice is None or voice.channel is None:
        return False
    return voice.channel != member.guild.afk_channel


def event_channels(guild):
    """IDs of the voice and stage channels of the Events in progress on a guild."""
    return {
        event.location.value.id
        for event in guild.scheduled_events
        if event.status is discord.ScheduledEventStatus.active
        # External Events (a link, a place) have a text location: no channel
        and not isinstance(event.location.value, str)
        }


def update_voice():
    global voice_last_update

    # Until ready (startup, reconnection), voice states aren't up to date:
    # restart counting from the next update, instead of counting the whole
    # disconnection with the members that were in voice before it
    if not client.is_ready():
        voice_last_update = None
        return

    now = time.monotonic()
    # Actual time since the previous update, not POLLING_INTERVAL: the loop
    # drifts, and an update can be late
    elapsed = 0 if voice_last_update is None else now - voice_last_update
    voice_last_update = now
    # Wall clock for the unique members: their last seen times survive restarts
    seen_at = time.time()

    for guild in client.guilds:
        in_call = [
            member for member in guild.members
            if member.bot is False and in_voice(member)
            ]
        events = event_channels(guild)
        in_event = [member for member in in_call if member.voice.channel.id in events]

        METRICS['VOICE_MEMBERS'].labels(guild=guild).set(len(in_call))
        METRICS['VOICE_SECONDS'].labels(guild=guild).inc(len(in_call) * elapsed)
        # A subset of the voice ones: members in an Event are in a call too
        METRICS['EVENT_VOICE_MEMBERS'].labels(guild=guild).set(len(in_event))
        METRICS['EVENT_VOICE_SECONDS'].labels(guild=guild).inc(len(in_event) * elapsed)
        METRICS['VOICE_UNIQUE_MEMBERS'].update(guild, in_call, seen_at)
        METRICS['EVENT_VOICE_UNIQUE_MEMBERS'].update(guild, in_event, seen_at)

    METRICS['VOICE_UNIQUE_MEMBERS'].expire(seen_at)
    METRICS['EVENT_VOICE_UNIQUE_MEMBERS'].expire(seen_at)
    prune_guilds(
        'VOICE_MEMBERS', 'EVENT_VOICE_MEMBERS',
        'VOICE_UNIQUE_MEMBERS', 'EVENT_VOICE_UNIQUE_MEMBERS',
        )


async def poll(update, timer):
    # Tasks start before the client connects: until it's ready, there are
    # no guilds yet, so each update is a no-op
    while not client.is_closed():
        logger.trace(f'[Exporter][✓] Entering loop ({update.__name__})')
        try:
            update()
        except Exception as e:
            logger.error(f'[Exporter] Unable to retrieve data [{e}]')

        await asyncio.sleep(timer)


@client.event
async def on_ready():
    # Fired again after a reconnection, once the guilds are loaded
    logger.info(
        f'[Exporter][✓] Connected as {client.user} '
        f'({len(client.guilds)} guilds)'
        )


@client.event
async def on_message(ctx):
    try:
        # Direct messages to the bot belong to no guild: not counted
        if ctx.guild is None:
            return
        if ctx.author.bot is False:
            METRICS['MESSAGES'].labels(guild=ctx.guild, member=ctx.author).inc()
    except Exception as e:
        logger.error(f'[Exporter] Unable to retrieve data [{e}]')


# Raw event: on_reaction_add only fires for messages still in the client's
# message cache (the last 1000 seen since startup), this one for every message
@client.event
async def on_raw_reaction_add(payload):
    try:
        # Only set for reactions within a guild, None in direct messages
        member = payload.member
        if member is None:
            return
        if member.bot is False:
            METRICS['REACTIONS'].labels(guild=member.guild, member=member).inc()
    except Exception as e:
        logger.error(f'[Exporter] Unable to retrieve data [{e}]')


def main():
    # Nothing works without it: fail now, not once everything is started
    if env_vars['DISCORD_TOKEN'] is None:
        logger.error('[Exporter][✗] ENV var DISCORD_TOKEN not found')
        sys.exit(1)

    # An S3 persistence file that couldn't be read would be overwritten by the
    # first save: exit instead, and let the container restart to try again
    if not check_s3():
        logger.error('[Exporter][✗] Persistence file unavailable')
        sys.exit(1)

    # Persist Counters every PERSIST_TIMER seconds
    periodic_save()

    # Scheduled Tasks (Launched every POLLING_INTERVAL seconds)
    for update in (update_ping, update_registered, update_online, update_boost, update_voice):
        client.loop.create_task(poll(update, env_vars['POLLING_INTERVAL']))

    start_http_server(env_vars['EXPORTER_PORT'])

    start_health_server(env_vars['HEALTH_PORT'])

    # Run Discord client
    # No retry here: client.run() closes its event loop when it fails, so the
    # client can't be run again. Exit instead, and let the container restart
    try:
        client.run(env_vars['DISCORD_TOKEN'])
    except Exception as e:
        logger.error(f'[Exporter][✗] Discord client.run failed [{e}]')
        sys.exit(1)
    finally:
        # Last save on the way out, so counts since the previous one are kept
        PersistentCounter.save_all()


if __name__ == '__main__':
    main()
