import logging
import os
import sys

import discord
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

import mogidb
from bot.app import App
from bot.config import load as load_config
from bot.queue import QueueModule
from bot.room import RoomConfigModule, RoomModule
from bot.server import ServerModule

logger = logging.getLogger(__name__)

# Load .env file for basic configuration
load_dotenv()

# Load our toml file for additional config
config = load_config("config.toml")

# Connect to API
api_token = os.getenv("ACCESS_TOKEN")
if api_token is None:
    logger.error("Failed to get API token! Set ACCESS_TOKEN in .env!")
    sys.exit(1)
    
db = mogidb.Client(config.api_endpoint, access_token=api_token)

# Load database
sqldb = create_async_engine("sqlite+aiosqlite:///dev_gutbuster.sqlite")

intents = discord.Intents.default()
app = App(intents=intents)

# Load commands
app.add_module(RoomModule(db))
app.add_module(RoomConfigModule(db))
app.add_module(QueueModule(config, app, db, sqldb))
app.add_module(ServerModule(config, db, sqldb, app))


# Fetch our token
token = os.getenv("DISCORD_TOKEN")
if token is not None:
    app.run(token)
else:
    logger.error("Failed to get discord token! Set DISCORD_TOKEN in .env!")
    sys.exit(1)
