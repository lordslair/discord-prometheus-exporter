# -*- coding: utf8 -*-

import itertools

import discord
import pytest

from prometheus_client import REGISTRY

import exporter

# Metrics live in the global Prometheus registry for the whole session,
# so each test uses its own guild/member names to never read another's values
_ids = itertools.count()


def unique(prefix):
    return f'{prefix}-{next(_ids)}'


def sample(name, **labels):
    """Current value of a metric sample, 0 if it doesn't exist yet."""
    return REGISTRY.get_sample_value(name, labels) or 0


class FakeMember:
    def __init__(self, bot=False, status=discord.Status.online, guild=None):
        self.name = unique('member')
        self.bot = bot
        self.status = status
        self.guild = guild

    # Labels are set from the objects themselves, like discord.py's Member
    def __str__(self):
        return self.name


class FakeGuild:
    def __init__(self, members=(), boosts=0):
        self.name = unique('guild')
        self.members = list(members)
        self.premium_subscription_count = boosts

    def __str__(self):
        return self.name


class FakeLoop:
    def create_task(self, coro):
        # Never scheduled: close it, so Python doesn't warn it wasn't awaited
        coro.close()


class FakeClient:
    def __init__(self, guilds=(), latency=0.042, closed=False, ready=True):
        self.guilds = list(guilds)
        self.latency = latency
        self.closed = closed
        self.ready = ready
        self.loop = FakeLoop()

    def is_closed(self):
        return self.closed

    def is_ready(self):
        return self.ready

    def run(self, token):
        pass


@pytest.fixture
def fake_client(monkeypatch):
    """Replace the exporter's Discord client by a fake one, no network."""
    client = FakeClient()
    monkeypatch.setattr(exporter, 'client', client)
    return client
