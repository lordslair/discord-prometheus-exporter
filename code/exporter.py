#!/usr/bin/env python3
# -*- coding: utf8 -*-

import asyncio
import discord
import time

from prometheus_client import start_http_server
from loguru import logger

from variables import env_vars
from metrics import METRICS


if env_vars['DISCORD_TOKEN'] is None:
    logger.error('[Exporter][✗] ENV var DISCORD_TOKEN not found')

try:
    # Intents are needed since 2020 for Mamber and Messages infos
    # Needs to be activates in bots preferences in discord portal
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


async def request_ping(timer):
    while client.is_ready:
        logger.trace('[Exporter][✓] Enterng loop')
        try:
            latency = client.latency
        except Exception as e:
            logger.error(f'[Exporter] Unable to retrieve data [{e}]')
        else:
            try:
                METRICS['PING'].set(latency)
            except Exception as e:
                logger.error(f'[Exporter] Unable to set DISCORD_PING [{e}]')

        await asyncio.sleep(timer)


async def request_registered(timer):
    while client.is_ready:
        logger.trace('[Exporter][✓] Enterng loop')
        try:
            if client.guilds:
                members_registered = 0
                bots_registered = 0
                for guild in client.guilds:
                    for member in guild.members:
                        if member.bot is False:
                            members_registered += 1
                        else:
                            bots_registered += 1
                    METRICS['BOTS_REGISTERED'].labels(
                        guild=guild
                        ).set(bots_registered)
                    METRICS['MEMBERS_REGISTERED'].labels(
                        guild=guild
                        ).set(members_registered)
        except Exception as e:
            logger.error(f'[Exporter] Unable to retrieve data [{e}]')

        await asyncio.sleep(timer)


async def request_online(timer):
    while client.is_ready:
        logger.trace('[Exporter][✓] Enterng loop')
        try:
            if client.guilds:
                members_online = 0
                bots_online = 0
                for guild in client.guilds:
                    for member in guild.members:
                        if member.bot is False:
                            if member.status is not discord.Status.offline:
                                members_online += 1
                        else:
                            if member.status is not discord.Status.offline:
                                bots_online += 1
                    METRICS['BOTS_ONLINE'].labels(
                        guild=guild
                        ).set(bots_online)
                    METRICS['MEMBERS_ONLINE'].labels(
                        guild=guild
                        ).set(members_online)
        except Exception as e:
            logger.error(f'[Exporter] Unable to retrieve data [{e}]')

        await asyncio.sleep(timer)


async def request_boost(timer):
    while client.is_ready:
        logger.trace('[Exporter][✓] Enterng loop')
        try:
            if client.guilds:
                for guild in client.guilds:
                    METRICS['BOOSTS'].labels(
                        guild=guild
                        ).set(guild.premium_subscription_count)
        except Exception as e:
            logger.error(f'[Exporter] Unable to retrieve data [{e}]')

        await asyncio.sleep(timer)

# Scheduled Tasks (Launched every POLLING_INTERVAL seconds)
client.loop.create_task(request_ping(env_vars['POLLING_INTERVAL']))
client.loop.create_task(request_registered(env_vars['POLLING_INTERVAL']))
client.loop.create_task(request_online(env_vars['POLLING_INTERVAL']))
client.loop.create_task(request_boost(env_vars['POLLING_INTERVAL']))

start_http_server(env_vars['EXPORTER_PORT'])


@client.event
async def on_message(ctx):
    try:
        if ctx.author.bot is False:
            METRICS['MESSAGES'].labels(guild=ctx.guild, member=ctx.author).inc()
    except Exception as e:
        logger.error(f'[Exporter] Unable to retrieve data [{e}]')


@client.event
async def on_reaction_add(reaction, member):
    try:
        if member.bot is False:
            METRICS['REACTIONS'].labels(guild=member.guild, member=member).inc()
    except Exception as e:
        logger.error(f'[Exporter] Unable to retrieve data [{e}]')

# Run Discord client
iter = 0
while iter < 5:
    try:
        client.run(env_vars['DISCORD_TOKEN'])
        break
    except Exception as e:
        logger.error(
            f'[Exporter][✗] '
            f'Discord client.run failed (Attempt: {iter+1}/5 [{e}])'
            )
        iter += 1
        time.sleep(5000000)
        continue
