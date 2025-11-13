from gutbuster.app import App
from gutbuster.user import get_or_create_user, get_user
from gutbuster.room import get_room
from gutbuster.event import get_latest_active_event, create_event, EventStatus, Event
from gutbuster.config import load as load_config

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
import discord
from discord import ui
from discord import AllowedMentions
import random
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Load .env file for basic configuration
load_dotenv()

# Load our toml file for additional config
config = load_config("config.toml")

intents = discord.Intents.default()
app = App(intents=intents)


class VoteView(ui.LayoutView):
    """
    A view that allows players to vote for their favorite format!
    """

    container = ui.Container()

    def __init__(self, header: str):
        super().__init__()
        self.container.add_item(ui.TextDisplay(header))


async def start_event(event: Event, conn: AsyncConnection) -> None:
    """
    Starts an event, notifying all waiting players.
    """

    # Set the started flag in the DB
    await event.set_status(EventStatus.STARTED, conn)

    # Notify players in the channel
    channel = event.room.channel

    content = ""
    allowed_mentions = AllowedMentions.none()
    allowed_mentions.users = []

    for i, participant in enumerate(event.get_participants()):
        discord_user = await participant.user.fetch_user(app)
        allowed_mentions.users.append(discord_user)

        if i > 0:
            # Add a space between mentions to make it more readable.
            content += f" {discord_user.mention}"
        else:
            content += f"{discord_user.mention}"

    # Add a special message to make this Mogi feel extra special <3
    if len(config.messages.gathered) > 0:
        random_message = random.choice(config.messages.gathered)
        content += f"\n{random_message}"

    view = VoteView(content)
    await channel.send(None, allowed_mentions=allowed_mentions, view=view)


@app.tree.command(name="c", description="Queue into the mogi")
async def command_c(interaction: discord.Interaction):
    """
    The /c command.

    Allows people to queue into the channel the command was sent in.
    """

    if interaction.channel is None:
        # Ignore any user commands
        raise ValueError("Command not being called in a guild context?")

    name = getattr(interaction.user, "nick", None) or interaction.user.global_name

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

        # Check if the mogi has enough players to start
        if (
            event.status == EventStatus.LFG
            and len(event.get_participants()) >= room.players_required
        ):
            await start_event(event, conn)

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

    name = getattr(interaction.user, "nick", None) or interaction.user.global_name

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
        if event is not None:
            await event.preload_participants(conn)

        if event is None or not event.has(user):
            await interaction.response.send_message(
                f"{name}, you're not in the queue.\nUse </c:{command_c.id}> to enter the queue.",
                ephemeral=True,
            )
        else:
            await event.leave(user, conn)
            player_count = len(event.participants or [])
            await interaction.response.send_message(
                f"{name} has dropped from the mogi -- {player_count} players\nUse </c:{command_c.id}> to enter the queue.",
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
        participants = []
        if event is not None:
            await event.preload_participants(conn)
            participants = event.get_participants()

        # Build the mogi list
        message = "**Mogi List**"
        for i, participant in enumerate(participants):
            res = await conn.execute(
                text("SELECT name, discord_user_id FROM user WHERE id = :user_id"),
                {"user_id": participant.user_id},
            )

            row = res.first()
            if row is None:
                raise ValueError(f"failed to get existing user {participant.user_id}")

            discord_user = participant.user.fetch_user(app)
            message += f"\n`{i + 1}.` {discord_user.mention}"

        await interaction.response.send_message(
            message, allowed_mentions=AllowedMentions.none()
        )


@app.tree.command(name="end", description="Ends the current mogi and starts a new one")
async def command_end(interaction: discord.Interaction):
    """
    The /end command.

    Concludes a mogi. Any player may start a new mogi in the channel by using
    /c.
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
                "This channel isn't set up for mogis!",
                ephemeral=True,
            )
            return

        # Get the currently active event
        event = await get_latest_active_event(room, conn)


# Fetch our token
token = os.getenv("DISCORD_TOKEN")
if token is not None:
    app.run(token)
else:
    logger.error("Failed to get discord token! Set DISCORD_TOKEN in .env!")
    sys.exit(1)
