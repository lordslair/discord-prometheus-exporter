#!/usr/bin/env python3
# -*- coding: utf8 -*-

import os
import time

from prometheus_client  import start_http_server, Gauge, Counter
from datetime           import datetime

# Shorted definition for actual now() with proper format
def mynow(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Log System imports
print(f'{mynow()} [Exporter][✓] System imports')

import asyncio
import discord

# Log Discord imports
print(f'{mynow()} [Exporter][✓] Discord imports')

# Exporter variables
DISCORD_TOKEN    = os.getenv('DISCORD_TOKEN', None)
if DISCORD_TOKEN is None:
    print(f'{mynow()} [Exporter][✗] ENV var DISCORD_TOKEN not found')
    exit()
EXPORTER_PORT    = int(os.getenv('EXPORTER_PORT', '8080'))
POLLING_INTERVAL = int(os.getenv('POLLING_INTERVAL', 10))
print(f'{mynow()} [Exporter][✓] Listening on :{EXPORTER_PORT}')
print(f'{mynow()} [Exporter][✓] Polling interval {POLLING_INTERVAL}s')

# Metrics definition
# Gauges
DISCORD_PING               = Gauge('discord_latency',
                                   'The time in milliseconds that discord took to respond to a REST request.')
DISCORD_MEMBERS_REGISTERED = Gauge('discord_members_registered',
                                   'The number of connected members on a Guild.',
                                   ['guild'])
DISCORD_MEMBERS_ONLINE     = Gauge('discord_members_online',
                                   'The number of online members on a Guild.',
                                   ['guild'])
DISCORD_BOTS_REGISTERED    = Gauge('discord_bots_registered',
                                   'The number of connected bots on a Guild.',
                                   ['guild'])
DISCORD_BOTS_ONLINE        = Gauge('discord_bots_online',
                                   'The number of online bots on a Guild.',
                                   ['guild'])
DISCORD_BOOSTS             = Gauge('discord_boosts',
                                   'The number of Server Boosts on a Guild.',
                                   ['guild'])

# Counters
DISCORD_MESSAGES           = Counter('discord_messages',
                                     'The number of messages sent on a Guild by a Member.',
                                     ['guild','member'])
DISCORD_REACTIONS           = Counter('discord_reactions',
                                     'The number of messages sent on a Guild by a Member.',
                                     ['guild','member'])

print(f'{mynow()} [Exporter][✓] Metrics defined')

try:
    # Intents are needed since 2020 for Mamber and Messages infos
    # Needs to be activates in bots preferences in discord portal
    intents = discord.Intents.default()
    intents.members = True
    intents.presences = True
    client = discord.Client(intents=intents)
except Exception as e:
    print(f'{mynow()} [Exporter][✗] Connection failed')
else:
    print(f'{mynow()} [Exporter][✓] Connection successed')

#
# Tasks definition
#

async def request_ping(timer):
    while client.is_ready:
        try:
            latency = client.latency
        except Exception as e:
            print(f'{mynow()} [Exporter][request_ping] Unable to retrieve data [{e}]')
        else:
            try:
                DISCORD_PING.set(latency)
            except Exception as e:
                print(f'{mynow()} [Exporter][request_ping] Unable to set DISCORD_PING')

        await asyncio.sleep(timer)

async def request_registered(timer):
    while client.is_ready:
        try:
            if client.guilds:
                members_registered = 0
                bots_registered    = 0
                for guild in client.guilds:
                    for member in guild.members:
                        if member.bot is False:
                            members_registered += 1
                        else:
                            bots_registered += 1
                    DISCORD_BOTS_REGISTERED.labels(guild = guild).set(bots_registered)
                    DISCORD_MEMBERS_REGISTERED.labels(guild = guild).set(members_registered)
        except Exception as e:
            print(f'{mynow()} [Exporter][request_members_registered] Unable to retrieve data [{e}]')

        await asyncio.sleep(timer)

async def request_online(timer):
    while client.is_ready:
        try:
            if client.guilds:
                members_online = 0
                bots_online    = 0
                for guild in client.guilds:
                    for member in guild.members:
                        if member.bot is False:
                            if member.status is not discord.Status.offline:
                                members_online += 1
                        else:
                            if member.status is not discord.Status.offline:
                                bots_online += 1
                    DISCORD_BOTS_ONLINE.labels(guild = guild).set(bots_online)
                    DISCORD_MEMBERS_ONLINE.labels(guild = guild).set(members_online)
        except Exception as e:
            print(f'{mynow()} [Exporter][request_members_online] Unable to retrieve data [{e}]')

        await asyncio.sleep(timer)

async def request_boost(timer):
    while client.is_ready:
        try:
            if client.guilds:
                for guild in client.guilds:
                    DISCORD_BOOSTS.labels(guild = guild).set(guild.premium_subscription_count)
        except Exception as e:
            print(f'{mynow()} [Exporter][request_boost] Unable to retrieve data [{e}]')

        await asyncio.sleep(timer)

# Scheduled Tasks (Launched every POLLING_INTERVAL seconds)
client.loop.create_task(request_ping(POLLING_INTERVAL))
client.loop.create_task(request_registered(POLLING_INTERVAL))
client.loop.create_task(request_online(POLLING_INTERVAL))
client.loop.create_task(request_boost(POLLING_INTERVAL))

start_http_server(EXPORTER_PORT)

@client.event
async def on_message(ctx):
    try:
        if ctx.author.bot is False:
            DISCORD_MESSAGES.labels(guild = ctx.guild, member = ctx.author).inc()
    except Exception as e:
        print(f'{mynow()} [Exporter][on_message] Unable to retrieve data [{e}]')

@client.event
async def on_reaction_add(reaction, member):
    try:
        if member.bot is False:
            DISCORD_REACTIONS.labels(guild = member.guild, member = member).inc()
    except Exception as e:
        print(f'{mynow()} [Exporter][on_reaction_add] Unable to retrieve data [{e}]')

# Run Discord client
iter = 0
while iter < 5:
    try:
        client.run(DISCORD_TOKEN)
        break
    except:
        print(f'{mynow()} [Exporter][✗] Discord client.run failed (Attempt: {iter+1}/5) ')
        iter += 1
        time.sleep(5)
        continue
