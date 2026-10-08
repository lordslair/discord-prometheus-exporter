# -*- coding: utf8 -*-

import json
import os
import tempfile
import threading

from loguru import logger
from prometheus_client import Counter

from models.s3 import S3Object
from variables import env_vars


# Centralized Persistence Manager
class PersistentCounter:
    """
    A Prometheus Counter wrapper with persistent storage across restarts.

    This class manages a Prometheus Counter metric and periodically saves its state
    (all label combinations and their values) to a JSON file. On startup, it restores
    the counter values from the file, ensuring that metric values are not lost when
    the process or container restarts.

    Attributes:
        counter (prometheus_client.Counter): The underlying Prometheus Counter.
        _name (str): The metric name.
        _registry (list): Class-level list of all PersistentCounter instances,
            and of the other persistent metrics saved along (UniqueMembers).

    Methods:
        __getattr__(name):
            Forward attribute access to the underlying Counter instance.
        _load_initial_values():
            Load counter values from the persistence file, if present.
        _state():
            This counter's entries for the persistence file.
        save_all():
            Class method. Save the state of all registered PersistentCounter instances to disk.
    """
    _registry = []

    def __init__(self, name, description, labels):
        """Initialize a PersistentCounter instance."""
        self.counter = Counter(name, description, labels)
        self._name = name
        PersistentCounter._registry.append(self)
        self._load_initial_values()

    def __getattr__(self, name):
        """Delegate attribute access to the underlying Counter instance."""
        return getattr(self.counter, name)

    def _load_initial_values(self):
        """
        Load counter values for this metric from the persistence file.

        Only loads entries matching this metric's name. If the file is missing,
        empty, or invalid, loading is skipped gracefully.
        """
        try:
            for key, value in read_state().items():
                metric, _, label_json = key.partition(':')
                # Exact name: other metrics may share its prefix
                if metric == f'{self._name}_total':
                    label_dict = json.loads(label_json)
                    self.counter.labels(**label_dict).inc(value)
        except S3Unavailable:
            # Reported once by check_s3, before the exporter exits
            pass
        except Exception as e:
            logger.error(f"Error loading persistence file [{env_vars['PERSIST_FILE']}]: {e}")
        else:
            if env_vars['PERSIST_FILE']:
                logger.debug(f"Loaded Counter for {self._name}")

    def _state(self):
        """This counter's entries for the persistence file, one per label set."""
        state = {}
        for metric in self.counter.collect():
            for sample in metric.samples:
                if sample.name.endswith('_total') and sample.value > 0:
                    key = f"{sample.name}:{json.dumps(sample.labels)}"
                    state[key] = sample.value
        return state

    @classmethod
    def save_all(cls):
        """
        Save the state of all registered PersistentCounter instances to disk.

        This method collects the entries of every registered instance (counters,
        and any other persistent metric providing a _state() method) and writes
        them to the persistence file as a single JSON object. Should be called
        periodically by a single thread or timer.
        """
        persist_file = env_vars['PERSIST_FILE']
        if persist_file:
            state = {}
            for instance in cls._registry:
                state.update(instance._state())
            if state:  # Only write if state is not empty
                if is_s3(persist_file):
                    write_s3(persist_file, state)
                else:
                    cls._write_atomic(persist_file, state)
                logger.trace(f"Saved Counter persistence [{persist_file}]")

    @staticmethod
    def _write_atomic(persist_file, state):
        """
        Write the state to a temporary file, then rename it over the persistence file.

        A crash mid-write leaves the previous file intact instead of a truncated
        one, which would reset every counter on the next start.
        """
        # Same directory, so the rename never crosses filesystems
        fd, tmp_file = tempfile.mkstemp(
            dir=os.path.dirname(os.path.abspath(persist_file)),
            prefix='.persist-',
            suffix='.tmp',
            )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(state, f)
            os.replace(tmp_file, persist_file)
        except BaseException:
            os.unlink(tmp_file)
            raise


def is_s3(persist_file):
    """Whether the persistence file is an S3 object (s3://bucket/key)."""
    return persist_file.startswith('s3://')


def s3_object(persist_file):
    """The S3 object of an s3://bucket/key persistence file."""
    bucket, _, key = persist_file.removeprefix('s3://').partition('/')
    if not bucket or not key:
        raise ValueError(f'Invalid S3 persistence file [{persist_file}], expected s3://bucket/key')
    return S3Object(bucket, key)


# S3 object content, fetched once for all the metrics loading from it:
# persistence file -> content (bytes, None if missing), or the fetch error
_s3_cache = {}
# Last payload written to S3: unchanged saves are skipped (each one is a request)
_s3_saved = {}


class S3Unavailable(Exception):
    """The S3 persistence file couldn't be read: check_s3 reports why."""


def read_s3(persist_file):
    """The S3 object's content, None if it doesn't exist. Raises if it can't be read."""
    if persist_file not in _s3_cache:
        try:
            _s3_cache[persist_file] = s3_object(persist_file).get()
        except Exception as e:
            _s3_cache[persist_file] = S3Unavailable(e)
    content = _s3_cache[persist_file]
    if isinstance(content, Exception):
        raise content
    return content


def write_s3(persist_file, state):
    """Replace the S3 object's content with this state, if it changed."""
    payload = json.dumps(state).encode('utf-8')
    if _s3_saved.get(persist_file) != payload:
        s3_object(persist_file).put(payload)
        _s3_saved[persist_file] = payload


def check_s3():
    """
    Whether the persistence file can be read, when it's an S3 object.

    Unlike a local file, reading it can fail for a while (network, storage):
    starting anyway would overwrite the saved state with an empty one.
    """
    persist_file = env_vars['PERSIST_FILE']
    if persist_file and is_s3(persist_file):
        try:
            read_s3(persist_file)
        except S3Unavailable as e:
            logger.error(f"Unable to read the persistence file [{persist_file}]: {e}")
            return False
    return True


def read_state():
    """Content of the persistence file, empty if disabled or missing."""
    persist_file = env_vars['PERSIST_FILE']
    if persist_file and is_s3(persist_file):
        content = read_s3(persist_file)
        return json.loads(content) if content else {}
    if persist_file and os.path.exists(persist_file):
        with open(persist_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def periodic_save():
    # A failed save must not stop the next ones (the timer below would never
    # be started again)
    try:
        PersistentCounter.save_all()
    except Exception as e:
        logger.error(f"Unable to save Counter persistence [{e}]")
    # Daemon, so it never keeps the process alive once the exporter exits
    timer = threading.Timer(env_vars['PERSIST_TIMER'], periodic_save)
    timer.daemon = True
    timer.start()
