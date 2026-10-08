# -*- coding: utf8 -*-

import threading

from loguru import logger
from prometheus_client import Gauge

from models.persistent_counter import PersistentCounter, S3Unavailable, read_state
from variables import env_vars

# Rolling windows the unique members are counted over, in seconds
WINDOWS = {
    '1d': 86400,
    '7d': 7 * 86400,
    '30d': 30 * 86400,
}


class UniqueMembers:
    """
    A Prometheus Gauge of the unique members seen on a Guild, over rolling windows.

    Prometheus can't count unique members from per Guild metrics, and a member
    label would make too many series: so the exporter keeps when each member
    was last seen, per Guild, and exports how many were seen within each window
    (one series per Guild and window).

    Members are forgotten once not seen for the longest window. Last seen times
    are saved with the PersistentCounters, so the windows survive restarts.

    Attributes:
        gauge (prometheus_client.Gauge): The underlying Prometheus Gauge.
        _name (str): The metric name.
        _seen (dict): Guild ID -> Member ID -> last seen (Unix time).
            IDs are strings, as they are in the persistence file.
    """

    def __init__(self, name, description):
        """Initialize a UniqueMembers instance."""
        self.gauge = Gauge(name, description, ['guild', 'window'])
        self._name = name
        self._seen = {}
        # Updated in the event loop, saved from the persistence timer thread
        self._lock = threading.Lock()
        PersistentCounter._registry.append(self)
        self._load_initial_values()

    def __getattr__(self, name):
        """Delegate attribute access to the underlying Gauge instance."""
        return getattr(self.gauge, name)

    @property
    def _key(self):
        """This metric's entry in the persistence file."""
        return f'{self._name}:seen'

    def _load_initial_values(self):
        """Load the last seen times from the persistence file, if any."""
        try:
            seen = read_state().get(self._key, {})
            self._seen = {
                guild_id: {member_id: float(last) for member_id, last in members.items()}
                for guild_id, members in seen.items()
                }
        except S3Unavailable:
            # Reported once by check_s3, before the exporter exits
            pass
        except Exception as e:
            logger.error(f"Error loading persistence file [{env_vars['PERSIST_FILE']}]: {e}")
        else:
            if env_vars['PERSIST_FILE']:
                logger.debug(f"Loaded Unique Members for {self._name}")

    def _state(self):
        """This metric's entry for the persistence file."""
        with self._lock:
            seen = {guild_id: dict(members) for guild_id, members in self._seen.items()}
        return {self._key: seen} if seen else {}

    def update(self, guild, members, now):
        """Mark these members of a Guild as seen now, and export its counts."""
        with self._lock:
            seen = self._seen.setdefault(str(guild.id), {})
            for member in members:
                seen[str(member.id)] = now
            for window, seconds in WINDOWS.items():
                count = sum(1 for last in seen.values() if last > now - seconds)
                self.gauge.labels(guild=guild, window=window).set(count)

    def expire(self, now):
        """Forget the members not seen for the longest window, on every Guild."""
        oldest = now - max(WINDOWS.values())
        with self._lock:
            for guild_id, seen in list(self._seen.items()):
                for member_id, last in list(seen.items()):
                    if last <= oldest:
                        del seen[member_id]
                # Includes the Guilds the bot left, once nobody is in the windows
                if not seen:
                    del self._seen[guild_id]
