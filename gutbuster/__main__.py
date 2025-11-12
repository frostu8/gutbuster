from gutbuster.app import App
from gutbuster.user import get_or_create_user
from gutbuster.room import get_room
from gutbuster.event import get_latest_active_event, create_event

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

    if interaction.channel is None:
        # Ignore any user commands
        raise ValueError("Command not being called in a guild context?")

    async with app.db.connect() as conn:
        # Fetch the user from the database
        user = await get_or_create_user(interaction.user, conn)

        # Find the room
        room = await get_room(interaction.channel, conn)
        if room is None or not room.enabled:
            await interaction.response.send_message(
                "This channel isn't set up for mogis! Try /c'ing somewhere else.",
                ephemeral=True,
            )
            return

        # Get the currently active event
        event = await get_latest_active_event(room, conn)
        if event is None:
            event = await create_event(room, conn)

        name = interaction.user.nick or interaction.user.global_name
        await interaction.response.send_message(
            f"{name} has joined the mogi -- x players",
        )
        await conn.commit()


# Fetch our token
token = os.getenv("DISCORD_TOKEN")
if token is not None:
    app.run(token)
else:
    logger.error("Failed to get discord token! Set DISCORD_TOKEN in .env!")
    sys.exit(1)
