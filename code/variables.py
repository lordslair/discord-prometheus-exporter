# -*- coding: utf8 -*-

import os

from loguru import logger

# Grab the environment variables
env_vars = {
    "DISCORD_TOKEN": os.environ.get("DISCORD_TOKEN"),
    "EXPORTER_PORT": int(os.getenv('EXPORTER_PORT', '8080')),
    "HEALTH_PORT": int(os.getenv('HEALTH_PORT', '8081')),
    "PERSIST_FILE": os.environ.get("PERSIST_FILE", None),
    "PERSIST_TIMER": int(os.environ.get("PERSIST_TIMER", 60)),
    "POLLING_INTERVAL": int(os.getenv('POLLING_INTERVAL', 10)),
}
# Never written to the logs in full
SECRET_VARS = ('DISCORD_TOKEN',)


def mask(value):
    """Keep only both ends, enough to tell which token is set."""
    # Too short to show anything without revealing most of it
    if len(value) < 20:
        return '********'
    return f'{value[:4]}...{value[-4:]}'


def log_env_vars():
    """Print the environment variables for debugging, secrets masked."""
    for var, value in env_vars.items():
        if var in SECRET_VARS and value is not None:
            value = mask(value)
        logger.debug(f"{var}: {value}")


log_env_vars()
