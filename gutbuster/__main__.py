from gutbuster.app import App
from gutbuster.user import get_or_create_user, get_user, User
from gutbuster.room import get_room, EventFormat
from gutbuster.event import get_latest_active_event, create_event, EventStatus, Event
from gutbuster.config import load as load_config

from dotenv import load_dotenv
from typing import List, Callable, Awaitable, Any, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
import discord
from discord import AllowedMentions, ButtonStyle, ui
import datetime
import asyncio
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

intents = discord.Intents.default()
app = App(intents=intents)


class VoteEntry(ui.Section):
    """
    A format with a list of votes.
    """

    format: EventFormat
    votes: List[User]

    anonymized: bool
    _disabled: bool
    quality: float
    votes_needed: int

    def __init__(
        self,
        format: EventFormat,
        func: Callable[[discord.Interaction, EventFormat], Awaitable[Any]],
        *,
        anonymized: bool = True,
        disabled: bool = False,
        quality: float = 1.0,
        votes_needed: int = 4,
    ):
        # Generate a button for each format
        class VoteButton(ui.Button):
            def __init__(self, *, disabled: bool = False):
                super().__init__(style=ButtonStyle.blurple, label="Vote", disabled=disabled)

            async def callback(self, interaction: discord.Interaction):
                await func(interaction, format)

        super().__init__(accessory=VoteButton(disabled=disabled))
        self.format = format
        self.votes = []

        self.anonymized = True
        self._disabled = disabled
        self.quality = quality
        self.votes_needed = votes_needed

        self.regenerate_label()

    @property
    def disabled(self):
        return self._disabled

    @disabled.setter
    def disabled(self, value: bool):
        self._disabled = value

        if isinstance(self.accessory, ui.Button):
            self.accessory.disabled = self._disabled

    def regenerate_label(self):
        label = f"**{self.format.name}** Quality: `{self.quality:.3f}`"

        if self.anonymized:
            for i in range(self.votes_needed):
                if i == 0:
                    label += "\n"

                # lol
                if i < len(self.votes):
                    label += "🟩"
                else:
                    label += "⬛"
        else:
            for i, user in enumerate(self.votes):
                if i > 0:
                    label += " "
                else:
                    label += "\n"

                if isinstance(user.user, discord.User | discord.Member):
                    label += f"{user.user.mention}"
                else:
                    label += f"@{user.name}"

        self.clear_items()
        self.add_item(ui.TextDisplay(label))


class VoteContainer(ui.Container):
    header: ui.TextDisplay = ui.TextDisplay("")


class VoteView(ui.LayoutView):
    """
    A view that allows players to vote for their favorite format!
    """

    container: VoteContainer = VoteContainer()

    message: Optional[discord.Message] = None
    event: Event
    formats: List[VoteEntry] = []
    votes_needed: int

    selected_format: Optional[EventFormat] = None
    expiry_time: datetime.datetime
    expiry_task: Optional[asyncio.Task]

    def __init__(self, event: Event, *, flavor: Optional[str] = None, votes_needed: int = 4, expiry_time: datetime.datetime):
        super().__init__()
        self.flavor_text = flavor

        self.event = event
        self.votes_needed = votes_needed

        self.expired = False
        self.expiry_time = expiry_time
        self.expiry_task = None

        for i, format in enumerate(event.room.formats):
            view = VoteEntry(format, self.vote, votes_needed=self.votes_needed)
            self.formats.append(view)
            self.container.add_item(view)

        self.update_header()

    def __del__(self):
        self.cancel_expiry()

    def cancel_expiry(self) -> None:
        if self.expiry_task:
            self.expiry_task.cancel()

    def allowed_mentions(self) -> AllowedMentions:
        allowed_mentions = AllowedMentions.none()
        allowed_mentions.users = [p.user.user for p in self.event.get_participants()]
        # return allowed_mentions
        return AllowedMentions.none()

    def update_header(self) -> None:
        header = ""
        for i, participant in enumerate(self.event.get_participants()):
            mention = f"@{participant.user.name}"
            if isinstance(participant.user.user, discord.User | discord.Member):
                mention = participant.user.user.mention

            if i > 0:
                # Add a space between mentions to make it more readable.
                header += f" {mention}"
            else:
                header += f"{mention}"

        if self.flavor_text is not None:
            header += f"\n{self.flavor_text}"

        if self.selected_format is None:
            header += (
                f"\n\nMogi `{self.event.short_id}` has gathered. Vote for a format."
                f" Voting ends when a format gets 4 votes, or <t:{math.trunc(self.expiry_time.timestamp())}:R>"
            )
        else:
            header += (
                f"\n\nMogi `{self.event.short_id}` has gathered."
                f" Voting concluded. Format {self.selected_format.name} selected!"
            )

        # update container
        self.container.header.content = header

    async def close_vote(self, *, cancel: bool = True) -> None:
        if cancel:
            self.cancel_expiry()

        votes = [v for v in self.formats]

        # Coin flip any ties
        random.shuffle(votes)
        votes.sort(key=lambda v: v.votes, reverse=True)

        self.selected_format = votes[0].format
        self.update_header()

        for format in self.formats:
            format.disabled = True

        # Update the message
        if self.message is not None:
            await self.message.edit(allowed_mentions=self.allowed_mentions(), view=self)

    async def _wait_until_expiry(self):
        now = datetime.datetime.now()
        await asyncio.sleep((self.expiry_time - now).total_seconds())

        # DON'T CANCEL THE THREAD CALLING THIS FUNCTION!
        await self.close_vote(cancel=False)

    def wait_until_expiry(self):
        """
        Waits until the vote expires, and then closes it.
        """

        loop = asyncio.get_event_loop()
        self.expiry_task = loop.create_task(self._wait_until_expiry())

    async def vote(self, interaction: discord.Interaction, format: EventFormat):
        should_close = False

        # Do nothing if the vote is closed.
        # Do nothing if this user isn't part of the mogi's starting selection
        if not self.expired and any(
            p.user.user.id == interaction.user.id for p in self.event.get_participants()
        ):
            # Remove user from other votes
            for entry in self.formats:
                old_len = len(entry.votes)
                entry.votes = [
                    u for u in entry.votes if not u.user.id == interaction.user.id
                ]

                # Only regenerate label if
                if not len(entry.votes) == old_len:
                    entry.regenerate_label()

            entry = next(v for v in self.formats if v.format == format)

            user = None
            async with app.db.connect() as conn:
                user = await get_user(interaction.user, conn)

            # Add user to list
            entry.votes.append(user)
            entry.regenerate_label()

            if len(entry.votes) >= self.votes_needed:
                should_close = True

        if should_close:
            await self.close_vote()

        # Redisplay modal
        await interaction.response.edit_message(
            allowed_mentions=self.allowed_mentions(), view=self
        )


async def start_event(event: Event, conn: AsyncConnection) -> None:
    """
    Starts an event, notifying all waiting players.
    """

    # Set the started flag in the DB
    await event.set_status(EventStatus.STARTED, conn)

    # Notify players in the channel
    channel = event.room.channel

    # Preload all users
    for participant in event.get_participants():
        await participant.user.fetch_user(app)

    # Add a special message to make this Mogi feel extra special <3
    random_message = None
    if len(config.messages.gathered) > 0:
        random_message = random.choice(config.messages.gathered)

    # Get expiry time
    expiry = datetime.timedelta(seconds=120)
    expiry_time = datetime.datetime.now() + expiry

    view = VoteView(event, flavor=random_message, expiry_time=expiry_time, votes_needed=4)
    view.message = await channel.send(allowed_mentions=view.allowed_mentions(), view=view)
    view.wait_until_expiry()


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
        if event is None or not event.has(user):
            await interaction.response.send_message(
                f"{name}, you're not in the queue.\nUse </c:{command_c.id}> to enter the queue.",
                ephemeral=True,
            )
        else:
            await event.leave(user, conn)

            player_count = len(event.get_participants())
            await interaction.response.send_message(
                f"{name} has dropped from the mogi -- {player_count} players\nUse </c:{command_c.id}> to enter the queue.",
            )

            if len(event.get_participants()) == 0:
                await event.delete(conn)

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
