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
DISCORD_TOKEN    = os.environ['DISCORD_TOKEN']
EXPORTER_PORT    = int(os.environ['EXPORTER_PORT'])
POLLING_INTERVAL = int(os.environ['POLLING_INTERVAL'])
print(f'{mynow()} [Exporter][✓] Listening on :{EXPORTER_PORT}')

# Metrics definition
# Gauges
DISCORD_PING               = Gauge('discord_latency',
                                   'The time in milliseconds that discord took to respond to a REST request.')

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


start_http_server(EXPORTER_PORT)

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
