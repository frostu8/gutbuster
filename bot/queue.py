from copy import copy
from math import floor, ceil
from dataclasses import dataclass
from gutbuster.model import (
    get_or_create_user,
    get_user,
    User,
    get_room,
    EventFormat,
    create_event,
    EventStatus,
    Event,
    get_event,
    get_active_events_for,
    Participant, Room, get_current_event, get_active_events, FormatSelectMode,
)
from gutbuster.servers import ServerWatcher

from bot.servers import ServersModule
from bot.config import load as load_config, Config
from bot.app import Module
from bot.ui import FormatSelector, FormatVote, QueueStatus
from bot.room import RoomModule

from dotenv import load_dotenv
from typing import List, Callable, Awaitable, Any, Optional, Dict, Tuple
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
import asyncio
import heapq


class UserActivity:
    """
    Tracks the activity of users by channel.
    """

    db: AsyncEngine
    client: discord.Client

    channel: discord.TextChannel
    member: discord.Member

    warning_task: Optional[asyncio.Task[None]]
    drop_task: Optional[asyncio.Task[None]]

    def __init__(self, db: AsyncEngine, client: discord.Client, channel: discord.TextChannel, member: discord.Member):
        self.db = db
        self.client = client

        self.channel = channel
        self.member = member

        self.warning_task = None
        self.drop_task = None

        self.task = None

    async def touch(self, *, member: Optional[discord.Member] = None):
        """
        Notifies that there was a change in the player's activity.
        """

        # Cancel current wait task
        if self.warning_task:
            self.warning_task.cancel()
        if self.drop_task:
            self.drop_task.cancel()

        if member:
            self.member = member

        now = datetime.now()

        async with self.db.connect() as conn:
            room = await get_room(self.channel, conn)

        if room is None:
            return

        drop_time = None
        if room.inactivity_drop_after > 0:
            drop_time = now + timedelta(seconds=room.inactivity_drop_after)
            self.drop_task = asyncio.create_task(self._drop(drop_time))

        if drop_time and room.inactivity_warning_after > 0:
            warning_time = now + timedelta(seconds=room.inactivity_warning_after)
            self.warning_task = asyncio.create_task(self._warning(warning_time, drop_time))

    async def _warning(self, warning_time: datetime, drop_time: datetime):
        now = datetime.now()

        # waiting time
        await asyncio.sleep(max((warning_time - now).seconds, 0))

        now = datetime.now()

        if drop_time > now:
            async with self.db.connect() as conn:
                # Fetch the user from the database
                user = await get_user(self.member, conn)
                if user is None:
                    # The user hasn't been added yet, just ignore
                    return

                # Get active events and filter
                events = await get_active_events_for(user, conn)

                try:
                    event = next(e for e in events if e.room.channel.id == self.channel.id)
                    should_warn = event.status == EventStatus.LFG
                except StopIteration:
                    # User left event, no need to warn
                    should_warn = False

            if should_warn:
                minutes = ceil((drop_time - now).seconds / 60)

                time_str = str(minutes)
                if minutes == 1:
                    time_str += " minute"
                else:
                    time_str += " minutes"

                await self.channel.send(
                    f"{self.member.mention}, please type something within {time_str} to keep your spot in the mogi",
                )

    async def _drop(self, drop_time: datetime):
        now = datetime.now()

        # waiting time
        await asyncio.sleep(max((drop_time - now).seconds, 0))

        async with self.db.connect() as conn:
            # Fetch the user from the database
            user = await get_user(self.member, conn)
            if user is None:
                # The user hasn't been added yet, just ignore
                return

            # Get active events and filter
            events = await get_active_events_for(user, conn)

            try:
                event = next(e for e in events if e.room.channel.id == self.channel.id)
            except StopIteration:
                # Nothing to do, user left event
                return

            if not event.status == EventStatus.LFG:
                # Nothing to do, event is no longer LFG
                return

            await event.preload_participants(conn)

            await event.leave(user, conn)
            await conn.commit()

            player_count = len(event.get_participants())

            await self.channel.send(
                f"{self.member.display_name} has dropped from the mogi"
                f" due to inactivity -- {player_count} players",
            )


class ActivityTracker:
    db: AsyncEngine
    client: discord.Client

    users: Dict[Tuple[int, int], UserActivity]

    def __init__(self, db: AsyncEngine, client: discord.Client):
        self.db = db
        self.client = client

        self.users = {}

    async def _process(self, channel: discord.TextChannel, member: discord.Member):
        # Find activity of user
        if (channel.id, member.id) not in self.users:
            self.users[(channel.id, member.id)] = UserActivity(self.db, self.client, channel, member)

        activity = self.users[(channel.id, member.id)]
        await activity.touch(member=member)

    async def on_message(self, message: discord.Message):
        if not isinstance(message.channel, discord.TextChannel):
            return
        if not isinstance(message.author, discord.Member):
            return

        if message.author.bot:
            return

        await self._process(message.channel, message.author)

    async def on_interaction(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            return
        if not isinstance(interaction.user, discord.Member):
            return

        if interaction.user.bot:
            return

        await self._process(interaction.channel, interaction.user)


class QueueModule(Module):
    """
    The queue module.

    Contains commands for players to interact with queues.
    """

    config: Config
    watcher: ServerWatcher
    db: AsyncEngine

    activity: ActivityTracker

    command_can: Optional[app_commands.AppCommand]
    command_drop: Optional[app_commands.AppCommand]

    def __init__(self, config: Config, watcher: ServerWatcher, client: discord.Client, db: AsyncEngine):
        self.config = config
        self.watcher = watcher
        self.db = db

        self.activity = ActivityTracker(db, client)

        self.command_can = None
        self.command_drop = None

    async def on_setup(self, tree: app_commands.CommandTree):
        commands = await tree.fetch_commands()

        self.command_drop = next(c for c in commands if c.name == "d")
        self.command_can = next(c for c in commands if c.name == "c")

    async def on_message(self, message: discord.Message):
        await self.activity.on_message(message)

    async def on_interaction(self, interaction: discord.Interaction):
        await self.activity.on_interaction(interaction)

    async def start_vote(
        self,
        event: Event,
        *,
        client: discord.Client,
        conn: AsyncConnection,
        flavor_text: Optional[str] = None
    ):
        channel = event.room.channel
        if isinstance(channel, discord.Object):
            channel = client.get_channel(channel.id)
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Mogi can only take place in a guild channel")

        # Assign temporary teams during voting phase to let the bot know to
        # restrict the player's movement
        participants = event.participants
        if participants is None:
            participants = await event.preload_participants(conn)

        for i, player in enumerate(participants):
            await player.assign_team(i, conn)

        view = FormatVote(
            client,
            self.config,
            self.watcher,
            self.db,
            event,
            flavor=flavor_text,
            timeout=120,
            votes_needed=event.room.votes_required,
        )
        view.message = await channel.send(
            allowed_mentions=view.allowed_mentions(), view=view
        )

    async def start_random(
        self,
        event: Event,
        *,
        client: discord.Client,
        conn: AsyncConnection,
        flavor_text: Optional[str] = None
    ):
        channel = event.room.channel
        if isinstance(channel, discord.Object):
            channel = client.get_channel(channel.id)
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Mogi can only take place in a guild channel")

        # Randomly select format
        # First, make sure we even have the formats
        await event.room.preload_formats(conn)

        formats = copy(event.room.formats)
        random.shuffle(formats)

        assert len(formats) > 0, "Room formats must not be empty"
        selected_format = formats.pop()

        # Assign format to event
        await event.set_format(selected_format, conn)

        # Find server for queue
        server = await selected_format.find_server(conn)
        if server is not None:
            await event.set_remote(server.remote, conn)

        # Create teams
        await event.assign_teams(conn)
        await conn.commit()

        # Notify users
        view = FormatSelector(
            event,
            flavor_text=flavor_text,
            timeout=120,
        )
        await channel.send(view=view, allowed_mentions=view.allowed_mentions())

        # Send new view
        view = QueueStatus(
            client,
            self.db,
            self.config,
            event,
            self.watcher,
        )

        await view.update()
        if view.has_realtime:
            view.realtime()

        view.message = await channel.send(view=view, allowed_mentions=AllowedMentions.none())

    async def start_event(
        self,
        event: Event,
        *,
        conn: AsyncConnection,
        client: discord.Client,
    ) -> None:
        """
        Starts an event, notifying all waiting players.
        """

        # Set the started flag in the DB
        await event.set_status(EventStatus.STARTED, conn)

        # Notify players in the channel
        channel = event.room.channel
        if isinstance(channel, discord.Object):
            channel = client.get_channel(channel.id)
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("Failed to get room channel")

        # Preload all users
        for participant in event.get_participants():
            await participant.user.fetch_user(client)

        # Add a special message to make this Mogi feel extra special <3
        flavor_text = None
        if len(self.config.messages.gathered) > 0:
            flavor_text = random.choice(self.config.messages.gathered)

        if event.room.format_selection_mode == FormatSelectMode.VOTE:
            await self.start_vote(event, conn=conn, client=client, flavor_text=flavor_text)
        elif event.room.format_selection_mode == FormatSelectMode.RANDOM:
            await self.start_random(event, conn=conn, client=client, flavor_text=flavor_text)

        # Uncan all participants from other mogis
        uncanned: Dict[int, List[User]] = {}
        for p in event.get_participants():
            canned_events = await get_active_events_for(p.user, conn)

            for canned in canned_events:
                # Don't uncan from our own event
                if canned.id == event.id:
                    continue
                # This probably shouldn't happen, but check if the event is
                # still LFG
                if not canned.status == EventStatus.LFG:
                    continue

                # Unregister from event
                await canned.leave(p.user, conn)

                if canned.room.channel.id not in uncanned.keys():
                    uncanned[canned.room.channel.id] = []
                uncanned[canned.room.channel.id].append(p.user)

                # Remove events if this empties the participant count
                if len(canned.get_participants()) == 0:
                    await canned.delete(conn)

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

        name = interaction.user.display_name

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

            # If the player is already assigned a team in a started mogi, they
            # shouldn't be able to join another
            active_events = await get_active_events_for(user, conn)
            for event in active_events:
                await event.preload_participants(conn)

                if event.is_user_playing(user):
                    channel = event.room.channel
                    if isinstance(channel, discord.Object):
                        channel = interaction.client.get_channel(channel.id)

                    assert isinstance(channel, discord.TextChannel), "Mogi in a non-guild context"

                    await interaction.response.send_message(
                        f"{name}, you are already playing in another queue."
                        f"\nYou must wait until the mogi in {channel.mention} has ended to can here.",
                        ephemeral=True,
                    )
                    return

            # Get the currently active event
            event = await get_current_event(room, conn)
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
                await self.start_event(event, conn=conn, client=interaction.client)

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

        name = interaction.user.display_name

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
            event = await get_current_event(room, conn)
            if event is None or not event.has(user):
                await interaction.response.send_message(
                    f"{name}, you're not in the queue.\nUse </c:{self.command_can.id}> to enter the queue.",
                    ephemeral=True,
                )
            else:
                if event.is_user_playing(user):
                    # The player has already been assigned a team. They
                    # shouldn't be able to /d
                    await interaction.response.send_message(
                        f"{name}, you are playing in this queue.\nYou must wait until the current mogi has ended.",
                        ephemeral=True,
                    )
                    return

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

        name = interaction.user.display_name

        async with self.db.connect() as conn:
            # Fetch the user from the database
            user = await get_or_create_user(interaction.user, conn)
            await conn.commit()

            events = await get_active_events_for(user, conn)
            for event in events:
                await event.preload_participants(conn)
                if event.is_user_playing(user):
                    # Skip any started mogis, as the user cannot leave them
                    continue

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

                if len(event.get_participants()) == 0:
                    await event.delete(conn)

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
            event = await get_current_event(room, conn)
            participants = []
            if event is not None:
                participants = event.participants or []

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


    @app_commands.command(name="ml", description="Lists all gathering and started mogis in the server")
    async def list_events(self, interaction: discord.Interaction):
        """
        The /ml command.

        Lists all gathering and started mogis in the server.
        """

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise ValueError("Command not being called in a guild context?")

        async with self.db.connect() as conn:
            # Find all events in a guild, and preload participants
            events = await get_active_events(interaction.channel.guild.id, conn)
            for event in events:
                await event.preload_participants(conn)

            # Count mogi
            event_count = len(events)
            started_event_count = sum(1 for e in events if e.status == EventStatus.STARTED)

            message = f"There are {event_count} active mogi and {started_event_count} full mogi."

            # Go into detail about each queue
            for event in events:
                player_count = len(event.get_participants())
                max_player_count = event.room.players_required

                channel = event.room.channel
                if isinstance(channel, discord.Object):
                    channel = interaction.client.get_channel(channel.id)
                if not isinstance(channel, discord.TextChannel):
                    raise ValueError("Mogi started in a non-text channel context")

                match event.status:
                    case EventStatus.STARTED:
                        status_icon = "⚡"
                    case _:
                        status_icon = ""

                # Create queue information
                message += (
                    f"\n\n{status_icon}{channel.mention} ({channel.name})"
                    f" - {player_count}/{max_player_count}\n"
                )
                for i, player in enumerate(event.get_participants()):
                    user = await player.user.fetch_user(interaction.client)

                    if i > 0:
                        message += f", {user.mention}"
                    else:
                        message += f"{user.mention}"

            await interaction.response.send_message(
                message, allowed_mentions=AllowedMentions.none()
            )


    async def _command_end(self, interaction: discord.Interaction):
        """
        The /end command.

        Ends the current mogi. To end a mogi, either the queue must have rotted
        or the mogi has started.
        """

        assert self.command_can

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise ValueError("Command not being called in a guild context?")

        member = interaction.user
        assert isinstance(member, discord.Member), "Command not run in a guild context"

        name = member.display_name

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
            event = await get_current_event(room, conn)
            if event is None:
                await interaction.response.send_message(
                    "A mogi hasn't started yet!",
                    ephemeral=True,
                )
                return

            # TODO: magic number
            rot_time = event.inserted_at + timedelta(minutes=50)

            now = datetime.now()
            rotted = now >= rot_time

            # Check if the user is trying to end a queue in LFG phase
            if (
                event.status == EventStatus.LFG
                and not rotted
            ):
                await interaction.response.send_message(
                    "The mogi queue may be cleared"
                    f" <t:{math.trunc(rot_time.timestamp())}:R>.",
                    ephemeral=True,
                )
                return

            # Check if the mogi has "started," but the format hasn't been
            # determined.
            if (
                event.status == EventStatus.STARTED
                and event.format is None
            ):
                await interaction.response.send_message(
                    "A vote is being held to determine the format.",
                    ephemeral=True,
                )
                return

            # Close the mogi
            await event.set_status(EventStatus.ENDED, conn)
            await conn.commit()

        await interaction.response.send_message(
            f"Mogi has been ended by {name}."
            f"\nJoin a new queue with </c:{self.command_can.id}>!",
        )


    @app_commands.command(name="end", description="Ends the current mogi")
    async def end(self, interaction: discord.Interaction):
        await self._command_end(interaction)


    @app_commands.command(name="esn", description="Ends the current mogi")
    async def esn(self, interaction: discord.Interaction):
        await self._command_end(interaction)


    @app_commands.command(name="clear", description="Ends the current mogi forcefully")
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
            event = await get_current_event(room, conn)
            if event is not None:
                # Close the mogi
                await event.set_status(EventStatus.ENDED, conn)
                await conn.commit()

        await interaction.response.send_message(
            "The mogi queue has been cleared.",
        )

    @app_commands.command(name="remove", description="Removes a player from the queue")
    @default_permissions(None)
    async def remove(self, interaction: discord.Interaction, user: discord.Member):
        """
        The /remove command.

        Removes a player from the queue.
        """

        assert isinstance(interaction.channel, TextChannel), "command not being called in a guild context"

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
            event = await get_current_event(room, conn)
            if event is None:
                await interaction.response.send_message(
                    f"Player {user.display_name} is not in the queue.",
                    ephemeral=True,
                )
                return

            await event.preload_participants(conn)

            # Find the given player
            try:
                player = next(p for p in event.get_participants() if p.user.user.id == user.id)
            except StopIteration:
                await interaction.response.send_message(
                    f"Player {user.display_name} is not in the queue.",
                    ephemeral=True,
                )
                return

            # Remove the player
            await event.leave(player.user, conn)
            # Remove event if this removes the last player
            if len(event.get_participants()) == 0:
                await event.delete(conn)

            await conn.commit()

        await interaction.response.send_message(
            f"{user.mention} has been removed from the queue.",
            allowed_mentions=AllowedMentions(users=[user]),
        )

