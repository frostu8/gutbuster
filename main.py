import sys
import os
from gutbuster.queue import QueueModule
from gutbuster.room import RoomModule
from gutbuster.sticky import StickyModule
from gutbuster.app import App
import discord
from gutbuster.servers import ServerWatcher
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import load_dotenv
import logging
from gutbuster.config import load as load_config
from gutbuster.servers import ServersModule

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
sticky = StickyModule()
app.add_module(sticky)

app.add_module(RoomModule(db))
app.add_module(QueueModule(config, watcher, app, db, sticky.server))
app.add_module(ServersModule(config, db, watcher))


# Fetch our token
token = os.getenv("DISCORD_TOKEN")
if token is not None:
    app.run(token)
else:
    logger.error("Failed to get discord token! Set DISCORD_TOKEN in .env!")
    sys.exit(1)
