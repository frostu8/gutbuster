from gutbuster.app import Module
from gutbuster.model import (
    get_or_create_user,
    get_user,
    User,
    get_room,
    EventFormat,
    get_active_event,
    create_event,
    EventStatus,
    Event,
    get_event,
    get_active_events_for,
)
from gutbuster.room import RoomModule
from gutbuster.config import load as load_config, Config
from gutbuster.servers import ServerWatcher, ServersModule

from dotenv import load_dotenv
from typing import List, Callable, Awaitable, Any, Optional, Dict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine, AsyncEngine
import discord
from discord import AllowedMentions, ButtonStyle, ui, app_commands, TextChannel
from discord.app_commands import default_permissions
from datetime import datetime, timedelta
import math
import random
import logging
import os
import sys


async def start_event(config: Config, client: discord.Client, db: AsyncEngine, event: Event, conn: AsyncConnection) -> None:
    """
    Starts an event, notifying all waiting players.
    """

    # Set the started flag in the DB
    await event.set_status(EventStatus.STARTED, conn)

    # Notify players in the channel
    channel = event.room.channel
    if isinstance(channel, discord.Object):
        channel = client.get_channel(channel.id)

    if channel is None or not isinstance(channel, discord.TextChannel):
        raise ValueError("Failed to get room channel")

    # Preload all users
    for participant in event.get_participants():
        await participant.user.fetch_user(client)

    # Add a special message to make this Mogi feel extra special <3
    random_message = None
    if len(config.messages.gathered) > 0:
        random_message = random.choice(config.messages.gathered)

    view = VoteView(
        db,
        event,
        flavor=random_message,
        timeout=120,
        votes_needed=event.room.votes_required,
    )
    view.message = await channel.send(
        allowed_mentions=view.allowed_mentions(), view=view
    )

    # Uncan all participants from other mogis
    uncanned: Dict[int, List[User]] = {}
    for p in event.get_participants():
        canned_events = await get_active_events_for(p.user, conn)

        for canned in canned_events:
            # Don't uncan from our own event
            if canned.id == event.id:
                continue
            # This probably shouldn't happen, but check if the event is still
            # LFG
            if not canned.status == EventStatus.LFG:
                continue

            # Unregister from event
            await canned.leave(p.user, conn)

            if canned.room.channel.id not in uncanned.keys():
                uncanned[canned.room.channel.id] = []
            uncanned[canned.room.channel.id].append(p.user)

    # Notify channels of mass uncanning
    for k, v in uncanned.items():
        other_channel = client.get_channel(k)
        if other_channel is None:
            # Silently avoid notifying non-existent channel
            continue
        if not isinstance(other_channel, discord.TextChannel):
            raise ValueError("mogi started in non-guild channel")

        content = ""
        for i, user in enumerate(v):
            # Get user
            discord_user = await user.fetch_user(client)

            if i == 0:
                content += discord_user.mention
            elif i < len(v) - 1:
                content += f", {discord_user.mention}"
            else:
                content += f" and {discord_user.mention}"

        # Humanize
        if len(v) == 1:
            content += " has "
        else:
            content += " have "

        content += f"been removed from the mogi because another mogi in {channel.mention} has gathered."
        await other_channel.send(content, allowed_mentions=AllowedMentions.none())


class VoteEntry(ui.Section):
    """
    A format with a list of votes.
    """

    db: AsyncEngine

    format: EventFormat
    votes: List[User]

    anonymized: bool
    quality: float
    votes_needed: int

    _disabled: bool

    def __init__(
        self,
        db: AsyncEngine,
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
                super().__init__(
                    style=ButtonStyle.blurple, label="Vote", disabled=disabled
                )

            async def callback(self, interaction: discord.Interaction):
                await func(interaction, format)

        super().__init__(accessory=VoteButton(disabled=disabled))
        self.db = db
        self.format = format
        self.votes = []

        self.anonymized = True
        self._disabled = disabled
        self.quality = quality
        self.votes_needed = votes_needed

        self.regenerate()

    @property
    def disabled(self):
        return self._disabled

    @disabled.setter
    def disabled(self, value: bool):
        self._disabled = value

        if self.accessory is ui.Button:
            self.accessory.disabled = self._disabled

    def regenerate(self):
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

    db: AsyncEngine

    container: VoteContainer = VoteContainer()

    message: Optional[discord.Message] = None
    event: Event
    formats: List[VoteEntry] = []
    votes_needed: int

    selected_format: Optional[EventFormat] = None
    timeout_time: datetime

    def __init__(
        self,
        db: AsyncEngine,
        event: Event,
        *,
        timeout: int | float = 120.0,
        flavor: Optional[str] = None,
        votes_needed: int = 4,
    ):
        super().__init__(timeout=timeout)
        self.db = db
        self.flavor_text = flavor

        self.message = None
        self.event = event
        self.votes_needed = votes_needed

        self.timeout_time = datetime.now() + timedelta(seconds=timeout)

        for i, format in enumerate(event.room.formats):
            view = VoteEntry(self.db, format, self.vote, votes_needed=self.votes_needed)
            self.formats.append(view)
            self.container.add_item(view)

        self.update_header()

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
                f" Voting ends when a format gets 4 votes, or <t:{math.trunc(self.timeout_time.timestamp())}:R>"
            )
        else:
            header += (
                f"\n\nMogi `{self.event.short_id}` has gathered."
                f" Voting concluded. **Format {self.selected_format.name} selected!**"
            )

        # update container
        self.container.header.content = header

    async def close_vote(self) -> None:
        """
        Closes the vote.

        This also calls `stop` to disable further interactions.
        """

        votes = [v for v in self.formats]

        # Coin flip any ties
        random.shuffle(votes)
        votes.sort(key=lambda v: v.votes, reverse=True)

        self.selected_format = votes[0].format
        self.update_header()

        for format in self.formats:
            format.disabled = True
            format.anonymized = False
            format.regenerate()

        if not self.is_finished():
            self.stop()

        # Commit the format selection
        async with self.db.connect() as conn:
            # In case the event was updated while we were waiting for voting
            self.event = await get_event(self.event.id, conn)
            await self.event.set_format(self.selected_format, conn)
            await conn.commit()

        # Update the message
        if self.message is not None:
            await self.message.edit(allowed_mentions=self.allowed_mentions(), view=self)

    async def on_timeout(self) -> None:
        await self.close_vote()

    async def vote(self, interaction: discord.Interaction, format: EventFormat):
        should_close = False

        # Do nothing if the vote is closed.
        # Do nothing if this user isn't part of the mogi's starting selection
        if self.selected_format is None and any(
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
                    entry.regenerate()

            entry = next(v for v in self.formats if v.format == format)

            async with self.db.connect() as conn:
                user = await get_user(interaction.user, conn)
                if user:
                    entry.votes.append(user)

            entry.regenerate()

            if len(entry.votes) >= self.votes_needed:
                should_close = True

        if should_close:
            await self.close_vote()

        # Redisplay modal
        await interaction.response.edit_message(
            allowed_mentions=self.allowed_mentions(), view=self
        )


class QueueModule(Module):
    """
    The queue module.

    Contains commands for players to interact with queues.
    """

    config: Config
    db: AsyncEngine

    command_can: Optional[app_commands.AppCommand]
    command_drop: Optional[app_commands.AppCommand]

    def __init__(self, config: Config, db: AsyncEngine):
        self.config = config
        self.db = db

        self.command_can = None
        self.command_drop = None

    async def on_setup(self, tree: app_commands.CommandTree) -> None:
        commands = await tree.fetch_commands()

        self.command_drop = next(c for c in commands if c.name == "d")
        self.command_can = next(c for c in commands if c.name == "c")

    @app_commands.command(name="c", description="Queue into the mogi")
    async def can(self, interaction: discord.Interaction):
        """
        The /c command.

        Allows people to queue into the channel the command was sent in.
        """

        assert self.command_drop

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise ValueError("Command not being called in a guild context?")

        name = getattr(interaction.user, "nick", None) or interaction.user.global_name

        async with self.db.connect() as conn:
            # Fetch the user from the database
            user = await get_or_create_user(interaction.user, conn)
            await conn.commit()

            # Find the room
            room = await get_room(interaction.channel, conn)
            if room is None or not room.enabled:
                await interaction.response.send_message(
                    "This channel isn't set up for mogis!\nTry /c'ing somewhere else.",
                    ephemeral=True,
                )
                return

            # We can't host a Mogi here if there are no formats!
            if len(room.formats) == 0:
                await interaction.response.send_message(
                    "This channel has no formats to run mogis on! (This may be a misconfiguraton, try asking)\nTry /c'ing somewhere else.",
                    ephemeral=True,
                )
                return

            # Get the currently active event
            event = await get_active_event(room, conn)
            if event is None:
                # Users can create mogis by simply canning in a channel.
                event = await create_event(room, conn)

            if event.has(user):
                await interaction.response.send_message(
                    f"{name}, you're already in the queue.\nUse </d:{self.command_drop.id}> to drop from the queue.",
                    ephemeral=True,
                )
            else:
                await event.join(user, conn)

                player_count = len(event.participants or [])
                await interaction.response.send_message(
                    f"{name} has joined the mogi -- {player_count} players\nUse </d:{self.command_drop.id}> to drop from the queue.",
                )

            # Check if the mogi has enough players to start
            if (
                event.status == EventStatus.LFG
                and len(event.get_participants()) >= room.players_required
            ):
                await start_event(self.config, interaction.client, self.db, event, conn)

            await conn.commit()


    @app_commands.command(name="d", description="Drop from the mogi")
    async def drop(self, interaction: discord.Interaction):
        """
        The /d command.

        Allows users to drop from the queue they have joined.
        """

        assert self.command_can

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise ValueError("Command not being called in a guild context?")

        name = getattr(interaction.user, "nick", None) or interaction.user.global_name

        async with self.db.connect() as conn:
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
            event = await get_active_event(room, conn)
            if event is None or not event.has(user):
                await interaction.response.send_message(
                    f"{name}, you're not in the queue.\nUse </c:{self.command_can.id}> to enter the queue.",
                    ephemeral=True,
                )
            else:
                await event.leave(user, conn)

                player_count = len(event.get_participants())
                await interaction.response.send_message(
                    f"{name} has dropped from the mogi -- {player_count} players\nUse </c:{self.command_can.id}> to enter the queue.",
                )

                if len(event.get_participants()) == 0:
                    await event.delete(conn)

            await conn.commit()


    @app_commands.command(name="da", description="Drop from all joined mogis")
    async def drop_all(self, interaction: discord.Interaction):
        """
        The /da command.

        Allows users to drop from all queues they have joined.
        """

        assert self.command_can

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise ValueError("Command not being called in a guild context?")

        name = getattr(interaction.user, "nick", None) or interaction.user.global_name

        async with self.db.connect() as conn:
            # Fetch the user from the database
            user = await get_or_create_user(interaction.user, conn)
            await conn.commit()

            events = await get_active_events_for(user, conn)
            for event in events:
                # Leave the event
                await event.leave(user, conn)

                channel = event.room.channel
                if isinstance(channel, discord.Object):
                    channel = interaction.client.get_channel(channel.id)

                if channel is None or not isinstance(channel, discord.TextChannel):
                    raise ValueError("Failed to get room channel")

                player_count = len(event.get_participants())
                await channel.send(
                    f"{name} has dropped from the mogi -- {player_count} players\nUse </c:{self.command_can.id}> to enter the queue.",
                )

            await conn.commit()
            await interaction.response.send_message(
                f"You have been dropped from {len(events)} mogis.", ephemeral=True
            )


    @app_commands.command(name="l", description="Lists all players in the mogi")
    async def list_players(self, interaction: discord.Interaction):
        """
        The /l command.

        Lists all users in the current room.
        """

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise ValueError("Command not being called in a guild context?")

        async with self.db.connect() as conn:
            # Find the room
            room = await get_room(interaction.channel, conn)
            if room is None or not room.enabled:
                await interaction.response.send_message(
                    "This channel isn't set up for mogis!",
                    ephemeral=True,
                )
                return

            # Get the currently active event
            event = await get_active_event(room, conn)
            if event is None:
                interaction.response.send_message(
                    "Nobody's in here! Why not get it started?",
                )
                return

            participants = event.get_participants()

            # Build the mogi list
            message = "**Mogi List**"
            for i, participant in enumerate(participants):
                res = await conn.execute(
                    text("SELECT name, discord_user_id FROM user WHERE id = :user_id"),
                    {"user_id": participant.user.id},
                )

                row = res.first()
                if row is None:
                    raise ValueError(f"failed to get existing user {participant.user.id}")

                discord_user = await participant.user.fetch_user(interaction.client)
                message += f"\n`{i + 1}.` {discord_user.mention}"

            await interaction.response.send_message(
                message, allowed_mentions=AllowedMentions.none()
            )


    async def _command_end(self, interaction: discord.Interaction):
        """
        The /end command.

        Ends the current mogi. To end a mogi, two conditions must be met:
        - The mogi has started.
        - The mogi has had a format selected.
        """

        assert self.command_can

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise ValueError("Command not being called in a guild context?")

        async with self.db.connect() as conn:
            # Find the room
            room = await get_room(interaction.channel, conn)
            if room is None or not room.enabled:
                await interaction.response.send_message(
                    "This channel isn't set up for mogis!",
                    ephemeral=True,
                )
                return

            # Get the currently active event
            event = await get_active_event(room, conn)
            if event is None or event.status == EventStatus.LFG:
                await interaction.response.send_message(
                    "A mogi hasn't started yet!",
                    ephemeral=True,
                )
                return

            # Check if the mogi has "started," but the format hasn't been
            # determined.
            if event.status == EventStatus.STARTED and event.format is None:
                await interaction.response.send_message(
                    "A vote is being held to determine the format.",
                    ephemeral=True,
                )
                return

            # Close the mogi
            await event.set_status(EventStatus.ENDED, conn)
            await conn.commit()

            await interaction.response.send_message(
                f"Mogi `{event.short_id}` has ended.\nJoin a new queue with </c:{self.command_can.id}>!",
            )


    @app_commands.command(name="end", description="Ends the current mogi")
    async def end(self, interaction: discord.Interaction):
        await self._command_end(interaction)


    @app_commands.command(name="esn", description="Ends the current mogi")
    async def esn(self, interaction: discord.Interaction):
        await self._command_end(interaction)


    @app_commands.command(name="clear", description="Forgets the current mogi")
    @default_permissions(None)
    async def clear(self, interaction: discord.Interaction):
        """
        The /clear command.

        Forcibly ends a mogi. Any player may start a new mogi in the channel by
        using /c.
        """

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise ValueError("Command not being called in a guild context?")

        async with self.db.connect() as conn:
            # Find the room
            room = await get_room(interaction.channel, conn)
            if room is None or not room.enabled:
                await interaction.response.send_message(
                    "This channel isn't set up for mogis!",
                    ephemeral=True,
                )
                return

            # Get the currently active event
            event = await get_active_event(room, conn)
            if event is not None:
                await event.delete(conn)

            await interaction.response.send_message(
                "The mogi queue has been cleared.",
            )

            await conn.commit()

