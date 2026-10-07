#!/usr/bin/env python3
# -*- coding: utf8 -*-

import asyncio
import discord
import sys
import threading

from flask import Flask, Response
from prometheus_client import start_http_server
from loguru import logger

from variables import env_vars
from metrics import METRICS
from models.persistent_counter import PersistentCounter, periodic_save

# ========== Health Check Setup ==========
app = Flask(__name__)


# We'll use the 'client' variable defined below in the health endpoint
@app.route('/healthz')
def health():
    if client.is_closed():
        return Response("DISCONNECTED", status=503)
    elif not client.is_ready():
        return Response("NOT_READY", status=503)
    else:
        return Response("OK", status=200)


def run_flask():
    # Use a port different from the Prometheus exporter (default 8001 here)
    app.run(
        debug=False,
        host='0.0.0.0',
        port=env_vars.get('HEALTH_PORT'),
        threaded=True,
        use_reloader=False,
        )
# ========================================


try:
    # Intents are needed since 2020 for Member and Messages infos
    # Needs to be activated in bots preferences in discord portal
    intents = discord.Intents.default()
    intents.members = True
    intents.presences = True
    client = discord.Client(intents=intents)
except Exception as e:
    logger.error(f'[Exporter][✗] Connection KO [{e}]')
else:
    logger.info('[Exporter][✓] Connection OK')


#
# Tasks definition
#

def update_ping():
    METRICS['PING'].set(client.latency)


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


def update_boost():
    for guild in client.guilds:
        METRICS['BOOSTS'].labels(guild=guild).set(guild.premium_subscription_count)


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
    if env_vars['DISCORD_TOKEN'] is None:
        logger.error('[Exporter][✗] ENV var DISCORD_TOKEN not found')

    # Persist Counters every PERSIST_TIMER seconds
    periodic_save()

    # Scheduled Tasks (Launched every POLLING_INTERVAL seconds)
    for update in (update_ping, update_registered, update_online, update_boost):
        client.loop.create_task(poll(update, env_vars['POLLING_INTERVAL']))

    start_http_server(env_vars['EXPORTER_PORT'])

    # ========== Start Flask Health Server in Thread ==========
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    # ========================================================

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
