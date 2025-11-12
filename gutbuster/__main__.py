from gutbuster.app import App
from gutbuster.user import get_or_init_user

from dotenv import load_dotenv
import discord
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Load .env file for basic configuration
load_dotenv()

intents = discord.Intents.default()
app = App(intents=intents)

@app.tree.command(name="c", description="Queue into the mogi")
async def command_c(interaction: discord.Interaction):
    """
    The /c command.

    Allows people to queue into the channel the command was sent in.
    """

    # Fetch the user from the database
    async with app.db.connect() as conn:
        user = await get_or_init_user(interaction.user, conn)
        await conn.commit()

# Fetch our token
token = os.getenv('DISCORD_TOKEN')
if token is not None:
    app.run(token)
else:
    logger.error('Failed to get discord token! Set DISCORD_TOKEN in .env!')
    sys.exit(1)

