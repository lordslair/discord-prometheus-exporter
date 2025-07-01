# -*- coding: utf8 -*-

import os

from loguru import logger

# Grab the environment variables
env_vars = {
    "DISCORD_TOKEN": os.environ.get("DISCORD_TOKEN"),
    "EXPORTER_PORT": int(os.getenv('EXPORTER_PORT', '8080')),
    "HEALTH_PORT": int(os.getenv('EXPORTER_PORT', '8081')),
    "PERSIST_FILE": os.environ.get("PERSIST_FILE", None),
    "PERSIST_TIMER": int(os.environ.get("PERSIST_TIMER", 60)),
    "POLLING_INTERVAL": int(os.getenv('POLLING_INTERVAL', 10)),
}
# Print the environment variables for debugging
for var, value in env_vars.items():
    logger.debug(f"{var}: {value}")
