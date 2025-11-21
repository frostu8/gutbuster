import discord
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from discord import app_commands
from discord.ext import tasks
from gutbuster.servers import ServerWatcher

logger = logging.getLogger(__name__)

class App(discord.Client):
    """
    Application.

    This sets up all the bot hooks, event listeners and Everything Else:tm: to
    make the thing work.
    """

    user: discord.ClientUser
    tree: app_commands.CommandTree

    db: AsyncEngine
    watcher: ServerWatcher

    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)

        # Create an instance of a command tree, which will hold all of our
        # application commands.
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        # Connects to a database.
        self.db = create_async_engine("sqlite+aiosqlite:///dev_gutbuster.sqlite")
        self.watcher = ServerWatcher(db=self.db)

        await self.watcher.load()
        self.knock_servers.start()

    async def on_ready(self) -> None:
        logger.info(f'Logged in as {self.user}')
        # Syncs the current commands with Discord
        await self.tree.sync()

    @tasks.loop(seconds=30.0)
    async def knock_servers(self) -> None:
        for server in self.watcher.iter():
            await server.knock()
