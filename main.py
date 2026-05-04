import sys
import os
from bot.queue import QueueModule
from bot.app import App
from bot.config import load as load_config
from bot.room import RoomModule
import discord
from gutbuster.servers import ServerWatcher
from bot.server import ServerModule
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import load_dotenv
import logging

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

# Load room commands
app.add_module(RoomModule(db))
app.add_module(QueueModule(config, watcher, app, db))
app.add_module(ServerModule(config, db, watcher, app))


# Fetch our token
token = os.getenv("DISCORD_TOKEN")
if token is not None:
    app.run(token)
else:
    logger.error("Failed to get discord token! Set DISCORD_TOKEN in .env!")
    sys.exit(1)
