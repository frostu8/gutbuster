from gutbuster.app import App
from gutbuster.user import get_or_create_user, get_user
from gutbuster.room import get_room
from gutbuster.event import get_latest_active_event, create_event

from dotenv import load_dotenv
from sqlalchemy import text
import discord
from discord import AllowedMentions
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

    name = interaction.user.nick or interaction.user.global_name

    commands = await app.tree.fetch_commands()
    command_d = next(c for c in commands if c.name == "d")

    async with app.db.connect() as conn:
        # Fetch the user from the database
        user = await get_or_create_user(interaction.user, conn)
        await conn.commit()

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

        await event.preload_participants(conn)
        if event.has(user):
            await interaction.response.send_message(
                f"{name}, you're already in the queue.\nUse </d:{command_d.id}> to drop from the queue.",
                ephemeral=True,
            )
        else:
            await event.join(user, conn)

            player_count = len(event.participants or [])
            await interaction.response.send_message(
                f"{name} has joined the mogi -- {player_count} players\nUse </d:{command_d.id}> to drop from the queue.",
            )

        await conn.commit()


@app.tree.command(name="d", description="Drop from the mogi")
async def command_d(interaction: discord.Interaction):
    """
    The /d command.

    Allows users to drop from the queue they have joined.
    """

    if interaction.channel is None:
        # Ignore any user commands
        raise ValueError("Command not being called in a guild context?")

    name = interaction.user.nick or interaction.user.global_name

    commands = await app.tree.fetch_commands()
    command_c = next(c for c in commands if c.name == "c")

    async with app.db.connect() as conn:
        # Fetch the user from the database
        user = await get_or_create_user(interaction.user, conn)
        await conn.commit()

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

        await event.preload_participants(conn)
        if event.has(user):
            await event.leave(user, conn)
            player_count = len(event.participants or [])
            await interaction.response.send_message(
                f"{name} has dropped from the mogi -- {player_count} players\nUse </c:{command_c.id}> to enter the queue.",
            )
        else:
            await interaction.response.send_message(
                f"{name}, you're not in the queue.\nUse </c:{command_c.id}> to enter the queue.",
                ephemeral=True,
            )

        await conn.commit()


@app.tree.command(name="l", description="Lists all players in the mogi")
async def command_l(interaction: discord.Interaction):
    """
    The /l command.

    Lists all users in the current room.
    """

    if interaction.channel is None:
        # Ignore any user commands
        raise ValueError("Command not being called in a guild context?")

    async with app.db.connect() as conn:
        # Fetch the user from the database
        user = await get_or_create_user(interaction.user, conn)
        await conn.commit()

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

        await event.preload_participants(conn)

        # Build the mogi list
        message = "**Mogi List**"
        for i, participant in enumerate(event.get_participants()):
            res = await conn.execute(
                text("SELECT name, discord_user_id FROM user WHERE id = :user_id"),
                {"user_id": participant.user_id},
            )

            row = res.first()
            if row is None:
                raise ValueError(f"failed to get existing user {participant.user_id}")

            discord_user = app.get_user(row.discord_user_id)
            if discord_user is None:
                # try to get from API if it isn't in cache
                discord_user = await app.fetch_user(row.discord_user_id)

            if discord_user is None:
                message += (f"\n`{i + 1}.` @{row.name}")
            else:
                message += (f"\n`{i + 1}.` {discord_user.mention}")

        await interaction.response.send_message(message, allowed_mentions=AllowedMentions.none())


# Fetch our token
token = os.getenv("DISCORD_TOKEN")
if token is not None:
    app.run(token)
else:
    logger.error("Failed to get discord token! Set DISCORD_TOKEN in .env!")
    sys.exit(1)
