import discord
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from discord import app_commands

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

    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)

        # Create an instance of a command tree, which will hold all of our
        # application commands.
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Connects to a database.
        self.db = create_async_engine("sqlite+aiosqlite:///dev_gutbuster.sqlite")

        # Registers some views and components with the discord.py client. For
        # now this is unpopulated.
        pass

    async def on_ready(self):
        logger.info(f'Logged in as {self.user}')
        # Syncs the current commands with Discord
        await self.tree.sync()
