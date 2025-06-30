# -*- coding: utf8 -*-

import json
import os
import threading

from loguru import logger
from prometheus_client import Counter

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
        _registry (list): Class-level list of all PersistentCounter instances.

    Methods:
        __getattr__(name):
            Forward attribute access to the underlying Counter instance.
        _load_initial_values():
            Load counter values from the persistence file, if present.
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
        persist_file = env_vars['PERSIST_FILE']
        if persist_file and os.path.exists(persist_file):
            try:
                with open(persist_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                for key, value in state.items():
                    if key.startswith(self.counter._name):
                        label_json = key.split(':', 1)[1]
                        label_dict = json.loads(label_json)
                        self.counter.labels(**label_dict).inc(value)
            except Exception as e:
                logger.error(f"Error loading persistence file [{persist_file}]: {e}")
            else:
                logger.debug(f"Loaded Counter for {self.counter._name}")

    @classmethod
    def save_all(cls):
        """
        Save the state of all registered PersistentCounter instances to disk.

        This method collects all label/value pairs from all counters and writes
        them to the persistence file as a single JSON object. Should be called
        periodically by a single thread or timer.
        """
        persist_file = env_vars['PERSIST_FILE']
        if persist_file:
            state = {}
            for instance in cls._registry:
                for metric in instance.counter.collect():
                    for sample in metric.samples:
                        if sample.name.endswith('_total') and sample.value > 0:
                            key = f"{sample.name}:{json.dumps(sample.labels)}"
                            state[key] = sample.value
            if state:  # Only write if state is not empty
                with open(persist_file, 'w', encoding='utf-8') as f:
                    json.dump(state, f)
                logger.trace(f"Saved Counter persistence [{persist_file}]")


def periodic_save():
    PersistentCounter.save_all()
    threading.Timer(env_vars['PERSIST_TIMER'], periodic_save).start()


periodic_save()
