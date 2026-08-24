import asyncio
import logging
import math
import random
from copy import copy
from datetime import UTC, datetime, timedelta
from math import ceil

import discord
from discord import AllowedMentions, TextChannel, app_commands
from discord.app_commands import default_permissions
from sqlalchemy.ext.asyncio import AsyncEngine

import mogidb
from bot.app import Module
from bot.config import Config
from bot.find_server import find_server
from bot.ui import FormatSelector, FormatVote, QueueStatus
from mogidb.model import Event, EventFormat, EventStatus, FormatSelectionMode, User, Room

logger = logging.getLogger(__name__)


async def upsert_user(member: discord.User | discord.Member, db: mogidb.Client) -> User:
    return await db.upsert_user(
        member.id,
        member.global_name or member.name,
    )


class UserActivity:
    """
    Tracks the activity of users by channel.
    """

    db: mogidb.Client
    client: discord.Client

    channel: discord.TextChannel
    member: discord.Member

    warning_task: asyncio.Task[None] | None
    drop_task: asyncio.Task[None] | None

    def __init__(self, db: mogidb.Client, client: discord.Client, channel: discord.TextChannel, member: discord.Member):
        self.db = db
        self.client = client

        self.channel = channel
        self.member = member

        self.warning_task = None
        self.drop_task = None

        self.task = None

    async def touch(self, *, member: discord.Member | None = None):
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

        now = datetime.now(UTC)

        # Fetch room from db
        guild_id = self.channel.guild.id
        assert guild_id is not None

        room = await self.db.get_room(guild_id, self.channel.id)
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
        now = datetime.now(UTC)

        # waiting time
        await asyncio.sleep(max((warning_time - now).seconds, 0))

        now = datetime.now(UTC)

        if drop_time > now:
            # Fetch the user from the database
            user = await upsert_user(self.member, self.db)

            # Get the guild
            guild = await self.db.get_guild(self.channel.guild.id)
            if guild is None:
                # If the guild doesn't exist, there isn't anything setup.
                return

            # Find the event
            events = await self.db.list_events(guild.id, active=True, user_id=user.id)
            try:
                event = next(e for e in events if e.room and e.room.id == self.channel.id)
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
        now = datetime.now(UTC)

        # waiting time
        await asyncio.sleep(max((drop_time - now).seconds, 0))

        # Fetch the user from the database
        user = await upsert_user(self.member, self.db)

        # Get the guild
        guild = await self.db.get_guild(self.channel.guild.id)
        if guild is None:
            # If the guild doesn't exist, there isn't anything setup.
            return

        # Find the event
        events = await self.db.list_events(guild.id, active=True, user_id=user.id)
        try:
            event = next(e for e in events if e.room and e.room.id == self.channel.id)
        except StopIteration:
            # User left event, nothing to do.
            return

        assert event.room

        if event.status != EventStatus.LFG:
            # Nothing to do, event is no longer LFG
            return

        # Leave event
        event = await self.db.leave_event(guild.id, event.room.id, event.id, user.id)
        await self.channel.send(
            f"{self.member.display_name} has dropped from the mogi"
            f" due to inactivity -- {len(event.players)} players",
        )


class ActivityTracker:
    db: mogidb.Client
    client: discord.Client

    users: dict[tuple[int, int], UserActivity]

    def __init__(self, db: mogidb.Client, client: discord.Client):
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
    sqldb: AsyncEngine
    db: mogidb.Client
    client: discord.Client

    activity: ActivityTracker

    command_can: app_commands.AppCommand | None
    command_drop: app_commands.AppCommand | None

    def __init__(self, config: Config, client: discord.Client, db: mogidb.Client, sqldb: AsyncEngine):
        self.config = config
        self.db = db
        self.sqldb = sqldb
        self.client = client

        self.activity = ActivityTracker(db, client)

        self.command_can = None
        self.commnd_drop = None

    async def mention(self, user: User) -> str:
        if user.discord_user_id is None:
            return f"@{user.display_name}"

        discord_user = self.client.get_user(user.discord_user_id)
        if discord_user is None:
            discord_user = await self.client.fetch_user(user.discord_user_id)

        return discord_user.mention

    async def on_setup(self, tree: app_commands.CommandTree):
        commands = await tree.fetch_commands()

        self.command_drop = next(c for c in commands if c.name == "d")
        self.command_can = next(c for c in commands if c.name == "c")

    async def on_message(self, message: discord.Message):
        await self.activity.on_message(message)

    async def on_interaction(self, interaction: discord.Interaction):
        await self.activity.on_interaction(interaction)

    async def ping_subjects(self, room: Room, event: Event | None, *, client: discord.Client):
        """
        Pings the fools that dare enter the Mogi Zone.
        """

        assert room.guild

        channel = client.get_channel(room.id)
        if not isinstance(channel, discord.TextChannel):
            channel = await client.fetch_channel(room.id)
        if not isinstance(channel, discord.TextChannel):
            raise TypeError("Mogi can only take place in a guild channel")

        role_map = {role.id: role for role in channel.guild.roles}

        content = ""
        mention_roles: list[discord.Role] = []

        # Follow the rules:
        # 1. Is a whitelist defined? Ping those guys.
        if len(room.role_whitelist) > 0:
            for i, role_id in enumerate(room.role_whitelist):
                role = role_map[role_id]
                mention_roles.append(role)

                if i > 0:
                    content += f" {role.mention}"
                else:
                    content += role.mention
        # 2. Fall through, don't ping ANYONE!!!
        else:
            return

        # Append waiting player count
        if event is None:
            needed_players = room.players_required
        else:
            needed_players = room.players_required - len(event.players)
        content += f" +{needed_players}"

        await channel.send(
            content=content,
            allowed_mentions=AllowedMentions(
                roles=mention_roles,
            ),
        )

    async def start_vote(
        self,
        event: Event,
        *,
        client: discord.Client,
        flavor_text: str | None = None
    ):
        assert event.room
        assert event.room.guild

        channel = client.get_channel(event.room.id)
        if not isinstance(channel, discord.TextChannel):
            channel = await client.fetch_channel(event.room.id)
        if not isinstance(channel, discord.TextChannel):
            raise TypeError("Mogi can only take place in a guild channel")

        view = FormatVote(
            client,
            self.config,
            self.db,
            event,
            flavor=flavor_text,
            timeout=120,
            votes_needed=event.room.votes_required,
        )
        await view.update()

        view.message = await channel.send(
            allowed_mentions=view.allowed_mentions(), view=view
        )

    async def start_random(
        self,
        event: Event,
        *,
        client: discord.Client,
        flavor_text: str | None = None
    ):
        assert event.room
        assert event.room.guild

        room = event.room
        guild = event.room.guild

        channel = client.get_channel(event.room.id)
        if not isinstance(channel, discord.TextChannel):
            channel = await client.fetch_channel(event.room.id)
        if not isinstance(channel, discord.TextChannel):
            raise TypeError("Mogi can only take place in a guild channel")

        # Randomly select format
        formats: list[EventFormat] = copy(event.room.formats or [])
        random.shuffle(formats)

        assert len(formats) > 0, "Room formats must not be empty"
        selected_format = formats.pop()

        selected_server = await find_server(event, format=selected_format, db=self.db)

        # Update event
        event = await self.db.update_event(
            event.room.guild.id,
            event.room.id,
            event.id,
            format=selected_format.id if selected_format is not None else None,
            server=selected_server.id if selected_server is not None else None,
        )

        # Create teams
        event = await self.db.assign_teams(guild.id, room.id, event.id)

        # Notify users
        view = FormatSelector(
            client,
            event,
            flavor_text=flavor_text,
            timeout=120,
        )
        await view.update()
        
        await channel.send(view=view, allowed_mentions=view.allowed_mentions())

        # Send new view
        view = QueueStatus(
            self.config,
            client,
            self.db,
            event,
        )
        await view.update()

        if view.has_realtime:
            view.realtime()

        view.message = await channel.send(view=view, allowed_mentions=AllowedMentions.none())

    async def start_event(
        self,
        event: Event,
        *,
        client: discord.Client,
    ) -> None:
        """
        Starts an event, notifying all waiting players.
        """

        assert event.room
        assert event.room.guild

        room = event.room
        guild = event.room.guild

        # Set the started flag in the DB
        # No longer necessary as the API does this automagically
        # await event.set_status(EventStatus.STARTED, conn)

        # Notify players in the channel
        channel = client.get_channel(room.id)
        if not isinstance(channel, discord.TextChannel):
            channel = await client.fetch_channel(room.id)
        if not isinstance(channel, discord.TextChannel):
            raise TypeError("Mogi can only take place in a guild channel")

        # Preload all users
        users_by_id: dict[str, discord.User] = {}
        for participant in event.players:
            discord_user_id = participant.user.discord_user_id
            if discord_user_id is None:
                continue

            user = client.get_user(discord_user_id)
            if user is None:
                user = await client.fetch_user(discord_user_id)

            users_by_id[participant.user.id] = user

        # Add a special message to make this Mogi feel extra special <3
        flavor_text = None
        if len(self.config.messages.gathered) > 0:
            flavor_text = random.choice(self.config.messages.gathered)

        if event.room.format_selection_mode == FormatSelectionMode.VOTE:
            await self.start_vote(event, client=client, flavor_text=flavor_text)
        elif event.room.format_selection_mode == FormatSelectionMode.RANDOM:
            await self.start_random(event, client=client, flavor_text=flavor_text)

        # Uncan all participants from other mogis
        uncanned: dict[int, list[User]] = {}
        for p in event.players:
            canned_events = await self.db.list_events(
                guild.id,
                active=True,
                user_id=p.user.id,
            )

            for canned in canned_events:
                assert canned.room

                # Don't uncan from our own event
                if canned.id == event.id:
                    continue
                # This probably shouldn't happen, but check if the event is
                # still LFG
                if canned.status != EventStatus.LFG:
                    continue

                # Unregister from event
                await self.db.leave_event(guild.id, room.id, event.id, p.user.id)

                if canned.room.id not in uncanned:
                    uncanned[canned.room.id] = []
                uncanned[canned.room.id].append(p.user)

        # Notify channels of mass uncanning
        for k, v in uncanned.items():
            other_channel = client.get_channel(k)
            if other_channel is None:
                # Silently avoid notifying non-existent channel
                continue
            if not isinstance(other_channel, discord.TextChannel):
                raise TypeError("mogi started in non-guild channel")

            content = ""
            for i, user in enumerate(v):
                # Get user
                mention = await self.mention(user)

                if i == 0:
                    content += mention
                elif i < len(v) - 1:
                    content += f", {mention}"
                else:
                    content += f" and {mention}"

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
        assert interaction.guild

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise TypeError("Command not being called in a guild context?")

        assert isinstance(interaction.user, discord.Member)

        name = interaction.user.display_name

        # Fetch the user from the database
        user = await upsert_user(interaction.user, self.db)

        # Get the room
        room = await self.db.get_room(interaction.guild.id, interaction.channel.id)
        if room is None or not room.enabled:
            await interaction.response.send_message(
                "This channel isn't set up for mogis!\nTry /c'ing somewhere else.",
                ephemeral=True,
            )
            return
        assert room.guild

        # We can't host a Mogi here if there are no formats!
        if not room.formats:
            await interaction.response.send_message(
                "This channel has no formats to run mogis on! (This may be a misconfiguraton, try asking)\nTry /c'ing somewhere else.",
                ephemeral=True,
            )
            return

        # Get the currently active event
        event = await self.db.get_current_event(room.guild.id, room.id)
        if event is None:
            # Users can create mogis by simply canning in a channel.
            event = await self.db.create_event(room.guild.id, room.id)

        # If the player is already assigned a team in a started mogi, they
        # shouldn't be able to join another
        active_events = await self.db.list_events(room.guild.id, active=True, user_id=user.id)
        for active_event in active_events:
            assert active_event.room

            # Skip the current event
            if active_event.id == event.id:
                continue

            if active_event.is_playing(user):
                channel = interaction.client.get_channel(active_event.room.id)
                if channel is None:
                    channel = interaction.client.fetch_channel(active_event.room.id)

                assert isinstance(channel, discord.TextChannel), "Mogi in a non-guild context"

                await interaction.response.send_message(
                    f"{name}, you are already playing in another queue."
                    f"\nYou must wait until the mogi in {channel.mention} has ended to can here.",
                    ephemeral=True,
                )
                return

        # Check if user is in the blacklist... if so, they can't can here.
        blacklist = {id for id in room.role_blacklist}
        blacklisted_roles = [role for role in interaction.user.roles if role.id in blacklist]

        if len(blacklisted_roles) > 0:
            # Get the first role that blacklisted them
            role = blacklisted_roles.pop()

            await interaction.response.send_message(
                f"{name}, you are blacklisted from playing in this queue.\n"
                f"*Blame: {role.mention}*",
                allowed_mentions=AllowedMentions.none(),
            )
            return

        # Check if user is in the whitelist before allowing them to can.
        whitelist = {id for id in room.role_whitelist}
        whitelisted_roles = [role for role in interaction.user.roles if role.id in whitelist]

        if len(whitelist) > 0 and len(whitelisted_roles) == 0:
            await interaction.response.send_message(
                f"{name}, you are not whitelisted to play in this queue.",
                ephemeral=True,
            )
            return

        # Check if user is already canned
        if any(p.user.id == user.id for p in event.players):
            content = f"{name}, you're already in the queue.\n"
            if not active_event.is_playing(user):
                content += f"Use {self.command_drop.mention} to drop from the queue."

            await interaction.response.send_message(content, ephemeral=True)
            return
        else:
            join_res = await self.db.join_event(room.guild.id, room.id, event.id, user.id)
            event = join_res.event

            player_count = len(event.players)
            await interaction.response.send_message(
                f"{name} has joined the mogi -- {player_count} players\nUse </d:{self.command_drop.id}> to drop from the queue.",
            )

        # Check if the mogi has enough players to start
        if join_res.started:
            await self.start_event(event, client=interaction.client)


    @app_commands.command(name="d", description="Drop from the mogi")
    async def drop(self, interaction: discord.Interaction):
        """
        The /d command.

        Allows users to drop from the queue they have joined.
        """

        assert interaction.guild
        assert self.command_can

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise TypeError("Command not being called in a guild context?")

        name = interaction.user.display_name

        # Fetch the user from the database
        user = await upsert_user(interaction.user, self.db)

        # Get the room
        room = await self.db.get_room(interaction.guild.id, interaction.channel.id)
        if room is None or not room.enabled:
            await interaction.response.send_message(
                "This channel isn't set up for mogis!",
                ephemeral=True,
            )
            return
        assert room.guild

        # Get the currently active event
        event = await self.db.get_current_event(room.guild.id, room.id)
        if event is None or all(p.user.id != user.id for p in event.players):
            await interaction.response.send_message(
                f"{name}, you're not in the queue.\nUse </c:{self.command_can.id}> to enter the queue.",
                ephemeral=True,
            )
            return

        if event.is_playing(user):
            # The player has already been assigned a team. They
            # shouldn't be able to /d
            await interaction.response.send_message(
                f"{name}, you are playing in this queue.\n"
                "You must wait until the current mogi has ended.",
                ephemeral=True,
            )
            return

        event = await self.db.leave_event(room.guild.id, room.id, event.id, user.id)

        player_count = len(event.players)
        await interaction.response.send_message(
            f"{name} has dropped from the mogi -- {player_count} players\n"
            f"Use </c:{self.command_can.id}> to enter the queue.",
        )


    @app_commands.command(name="da", description="Drop from all joined mogis")
    async def drop_all(self, interaction: discord.Interaction):
        """
        The /da command.

        Allows users to drop from all queues they have joined.
        """

        assert self.command_can
        assert interaction.guild

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise TypeError("Command not being called in a guild context?")

        name = interaction.user.display_name

        # Get the guild
        guild = await self.db.get_guild(interaction.guild.id)
        if guild is None:
            # Weird jank ass fallthrough for when a server has no config.
            await interaction.response.send_message(
                "You have been dropped from 0 mogis.",
                ephemeral=True,
            )
            return

        # Fetch the user from the database
        user = await upsert_user(interaction.user, self.db)

        active_events = await self.db.list_events(guild.id, active=True, user_id=user.id)
        left_events_count = 0

        for event in active_events:
            assert event.room

            room = event.room

            if event.is_playing(user):
                # Skip any started mogis, as the user cannot leave them
                continue

            # Leave the event
            event = await self.db.leave_event(guild.id, room.id, event.id, user.id)

            channel = interaction.client.get_channel(room.id)
            if not isinstance(channel, discord.TextChannel):
                channel = interaction.client.fetch_channel(room.id)

            if channel is None or not isinstance(channel, discord.TextChannel):
                raise ValueError("Failed to get room channel")

            player_count = len(event.players)
            await channel.send(
                f"{name} has dropped from the mogi -- {player_count} players\nUse </c:{self.command_can.id}> to enter the queue.",
            )

            left_events_count += 1

        await interaction.response.send_message(
            f"You have been dropped from {left_events_count} mogis.",
            ephemeral=True,
        )


    @app_commands.command(name="l", description="Lists all players in the mogi")
    async def list_players(self, interaction: discord.Interaction):
        """
        The /l command.

        Lists all users in the current room.
        """

        assert interaction.guild

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise TypeError("Command not being called in a guild context?")

        # Get the room
        room = await self.db.get_room(interaction.guild.id, interaction.channel.id)
        if room is None or not room.enabled:
            await interaction.response.send_message(
                "This channel isn't set up for mogis!",
                ephemeral=True,
            )
            return
        assert room.guild

        # Get the currently active event
        event = await self.db.get_current_event(room.guild.id, room.id)

        # Build the mogi list
        message = "**Mogi List**"
        for i, participant in enumerate(event.players if event is not None else []):
            mention = await self.mention(participant.user)

            message += f"\n`{i + 1}.` {mention}"

        await interaction.response.send_message(
            message, allowed_mentions=AllowedMentions.none()
        )


    @app_commands.command(name="ml", description="Lists all gathering and started mogis in the server")
    async def list_events(self, interaction: discord.Interaction):
        """
        The /ml command.

        Lists all gathering and started mogis in the server.
        """

        assert interaction.guild

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise TypeError("Command not being called in a guild context?")

        # Get the guild
        guild = await self.db.get_guild(interaction.guild.id)
        if guild is None:
            # Weird jank ass fallthrough for when a server has no config.
            await interaction.response.send_message(
                "There are 0 active mogi and 0 ful mogi.",
                ephemeral=True,
            )
            return

        events = await self.db.list_events(guild.id, active=True)

        # Skip empty events
        events = [event for event in events if len(event.players) > 0]

        # Count mogi
        event_count = len(events)
        started_event_count = sum(1 for e in events if e.status == EventStatus.ONGOING)

        message = f"There are {event_count} active mogi and {started_event_count} full mogi."

        # Go into detail about each queue
        for event in events:
            assert event.room

            player_count = len(event.players)
            max_player_count = event.room.players_required

            channel = interaction.client.get_channel(event.room.id)
            if not isinstance(channel, discord.TextChannel):
                channel = await interaction.client.fetch_channel(event.room.id)

            assert isinstance(channel, discord.TextChannel), "Cannot hold mogis in non-text channels"

            match event.status:
                case EventStatus.ONGOING:
                    status_icon = "⚡"
                case _:
                    status_icon = ""

            # Create queue information
            message += (
                f"\n\n{status_icon}{channel.mention} ({channel.name})"
                f" - {player_count}/{max_player_count}\n"
            )
            for i, player in enumerate(event.players):
                mention = await self.mention(player.user)

                if i > 0:
                    message += f", {mention}"
                else:
                    message += f"{mention}"

        await interaction.response.send_message(
            message, allowed_mentions=AllowedMentions.none()
        )


    async def _command_end(self, interaction: discord.Interaction):
        """
        The /end command.

        Ends the current mogi. To end a mogi, either the queue must have rotted
        or the mogi has started.
        """

        assert interaction.guild
        assert self.command_can

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise TypeError("Command not being called in a guild context?")

        member = interaction.user
        assert isinstance(member, discord.Member), "Command not run in a guild context"

        name = member.display_name

        # Get the room
        room = await self.db.get_room(interaction.guild.id, interaction.channel.id)
        if room is None or not room.enabled:
            await interaction.response.send_message(
                "This channel isn't set up for mogis!",
                ephemeral=True,
            )
            return
        assert room.guild

        # Get the currently active event
        event = await self.db.get_current_event(room.guild.id, room.id)
        if event is None:
            await interaction.response.send_message(
                "A mogi hasn't started yet!",
                ephemeral=True,
            )
            return

        rot_time = event.created_at + timedelta(minutes=50)

        now = datetime.now(UTC)
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
            event.status == EventStatus.ONGOING
            and event.format is None
        ):
            await interaction.response.send_message(
                "A vote is being held to determine the format."
                " Accept your 4v4 fate.",
                ephemeral=True,
            )
            return

        # Close the mogi
        await self.db.update_event(room.guild.id, room.id, event.id, status=EventStatus.CONCLUDED)

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

    @app_commands.command(name="ping", description="Notifies associated roles of a gathering mogi")
    async def command_ping(self, interaction: discord.Interaction):
        assert interaction.guild

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise TypeError("Command not being called in a guild context?")

        # Get the room
        room = await self.db.get_room(interaction.guild.id, interaction.channel.id)
        if room is None or not room.enabled:
            await interaction.response.send_message(
                "This channel isn't set up for mogis!",
                ephemeral=True,
            )
            return
        assert room.guild

        # Get the currently active event
        event = await self.db.get_current_event(room.guild.id, room.id)
        await self.ping_subjects(room, event, client=interaction.client)

        # Tell user we did a good job :D
        await interaction.response.send_message(content="👍", ephemeral=True)

    @app_commands.command(name="clear", description="Ends the current mogi forcefully")
    @default_permissions(None)
    async def clear(self, interaction: discord.Interaction):
        """
        The /clear command.

        Forcibly ends a mogi. Any player may start a new mogi in the channel by
        using /c.
        """

        assert interaction.guild

        if not isinstance(interaction.channel, TextChannel):
            # Ignore any user commands
            raise TypeError("Command not being called in a guild context?")

        # Get the room
        room = await self.db.get_room(interaction.guild.id, interaction.channel.id)
        if room is None or not room.enabled:
            await interaction.response.send_message(
                "This channel isn't set up for mogis!",
                ephemeral=True,
            )
            return
        assert room.guild

        # Get the currently active event
        event = await self.db.get_current_event(room.guild.id, room.id)
        if event is None:
            await interaction.response.send_message(
                "A mogi hasn't started yet!",
                ephemeral=True,
            )
            return

        # Close the mogi
        await self.db.update_event(room.guild.id, room.id, event.id, status=EventStatus.CONCLUDED)

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

        assert interaction.guild

        assert isinstance(interaction.channel, TextChannel), "command not being called in a guild context"

        # Get the room
        room = await self.db.get_room(interaction.guild.id, interaction.channel.id)
        if room is None or not room.enabled:
            await interaction.response.send_message(
                "This channel isn't set up for mogis!",
                ephemeral=True,
            )
            return
        assert room.guild

        # Get the currently active event
        event = await self.db.get_current_event(room.guild.id, room.id)
        players = event.players if event is not None else []

        # Find the given player
        try:
            player = next(p for p in players if p.user.discord_user_id == user.id)
        except StopIteration:
            await interaction.response.send_message(
                f"Player {user.display_name} is not in the queue.",
                ephemeral=True,
            )
            return


        assert event

        # Remove the player
        await self.db.leave_event(room.guild.id, room.id, event.id, player.user.id)

        await interaction.response.send_message(
            f"{user.mention} has been removed from the queue.",
            allowed_mentions=AllowedMentions(users=[user]),
        )

