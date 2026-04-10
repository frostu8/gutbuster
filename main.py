from gutbuster.queue import QueueModule
from gutbuster.app import App
from gutbuster.model import (
    get_or_create_user,
    get_user,
    User,
    get_room,
    EventFormat,
    create_event,
    EventStatus,
    Event,
    get_event,
    get_active_events_for,
)
from gutbuster.room import RoomModule
from gutbuster.config import load as load_config
from gutbuster.servers import ServerWatcher, ServersModule

from dotenv import load_dotenv
from typing import List, Callable, Awaitable, Any, Optional, Dict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
import discord
from discord import AllowedMentions, ButtonStyle, ui
from discord.app_commands import default_permissions
from datetime import datetime, timedelta
import math
import random
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Load .env file for basic configuration
load_dotenv()

# Load our toml file for additional config
config = load_config("config.toml")

# Load database
db = create_async_engine("sqlite+aiosqlite:///dev_gutbuster.sqlite")
watcher = ServerWatcher(db)

intents = discord.Intents.default()
app = App(intents=intents)
app.db = db # TODO: Not do this.

# Load room commands
app.add_module(RoomModule(db))
app.add_module(QueueModule(config, app, db))
app.add_module(ServersModule(config, db, watcher))


# Fetch our token
token = os.getenv("DISCORD_TOKEN")
if token is not None:
    app.run(token)
else:
    logger.error("Failed to get discord token! Set DISCORD_TOKEN in .env!")
    sys.exit(1)
