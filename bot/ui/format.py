import logging
import math
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from discord import AllowedMentions, ButtonStyle, ui

import mogidb
from bot.config import Config
from mogidb import Unset
from mogidb.model import Event, EventFormat, User

from .queue import QueueStatus

logger = logging.getLogger(__name__)


class FormatSelectorContainer(ui.Container):
    client: discord.Client

    event: Event
    format: EventFormat

    flavor_text: str | None = None

    header: ui.TextDisplay = ui.TextDisplay("")

    def __init__(self, client: discord.Client, event: Event, format: EventFormat, *, flavor_text: str | None = None):
        super().__init__()
        self.client = client
        self.event = event
        self.format = format

        self.flavor_text = flavor_text

    async def update(self):
        # Generate header content
        content = ""
        for i, participant in enumerate(self.event.players):
            mention = f"@{participant.user.display_name}"
            if participant.user.discord_user_id is not None:
                discord_user = self.client.get_user(participant.user.discord_user_id)
                if discord_user is None:
                    discord_user = await self.client.fetch_user(participant.user.discord_user_id)

                mention = discord_user.mention

            if i > 0:
                # Add a space between mentions to make it more readable.
                content += f" {mention}"
            else:
                content += f"{mention}"

        if self.flavor_text is not None:
            content += f"\n{self.flavor_text}"

        content += (
            f"\n\nMogi has gathered."
            f"\nThe wheel has sealed your fate. **Format __{self.format.name}__ selected!**"
        )

        # update container
        self.header.content = content
        


class FormatSelector(ui.LayoutView):
    """
    A barebones version of `FormatVote` that only mentions the queue with the
    chosen format.
    """

    client: discord.Client
    event: Event

    container: FormatSelectorContainer

    def __init__(
        self,
        client: discord.Client,
        event: Event,
        *,
        timeout: float = 120,
        flavor_text: str | None = None,
    ):
        super().__init__(timeout=timeout)
        self.client = client

        if event.format is None:
            raise ValueError("The passed event must have a format selected")

        self.event = event
        self.container = FormatSelectorContainer(client, event, event.format, flavor_text=flavor_text)

        self.add_item(self.container)

    async def update(self):
        await self.container.update()

    def allowed_mentions(self) -> AllowedMentions:
        allowed_mentions = AllowedMentions.none()
        allowed_mentions.users = [discord.Object(p.user.discord_user_id) for p in self.event.players if p.user.discord_user_id]
        return allowed_mentions


class VoteButton(ui.Button):
    format: EventFormat
    func: Callable[[discord.Interaction, EventFormat], Awaitable[Any]]

    def __init__(self, format: EventFormat, func: Callable[[discord.Interaction, EventFormat], Awaitable[Any]], *, disabled: bool = False):
        super().__init__(
            style=ButtonStyle.blurple, label="Vote", disabled=disabled
        )
        self.format = format
        self.func = func

    async def callback(self, interaction: discord.Interaction):
        await self.func(interaction, self.format)


class VoteEntry(ui.Section):
    """
    A format with a list of votes.
    """

    client: discord.Client
    db: mogidb.Client

    format: EventFormat
    votes: list[User]

    anonymized: bool
    quality: float
    votes_needed: int

    _disabled: bool

    def __init__(
        self,
        client: discord.Client,
        db: mogidb.Client,
        format: EventFormat,
        func: Callable[[discord.Interaction, EventFormat], Awaitable[Any]],
        *,
        anonymized: bool = True,
        disabled: bool = False,
        quality: float = 1.0,
        votes_needed: int = 4,
    ):
        super().__init__(accessory=VoteButton(format, func, disabled=disabled))
        self.client = client
        self.db = db
        self.format = format
        self.votes = []

        self.anonymized = anonymized
        self._disabled = disabled
        self.quality = quality
        self.votes_needed = votes_needed

    @property
    def disabled(self):
        return self._disabled

    @disabled.setter
    def disabled(self, value: bool):
        self._disabled = value

        if isinstance(self.accessory, VoteButton):
            self.accessory.disabled = self._disabled

    async def update(self):
        #label = f"**{self.format.name}** Quality: `{self.quality:.3f}`"
        label = f"**{self.format.name}**"

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

                mention = f"@{user.display_name}"
                if user.discord_user_id is not None:
                    discord_user = self.client.get_user(user.discord_user_id)
                    if discord_user is None:
                        discord_user = await self.client.fetch_user(user.discord_user_id)

                    mention = discord_user.mention

                label += mention

        self.clear_items()
        self.add_item(ui.TextDisplay(label))


class VoteContainer(ui.Container):
    header: ui.TextDisplay = ui.TextDisplay("")


class FormatVote(ui.LayoutView):
    """
    A view that allows players to vote for their favorite format!
    """

    client: discord.Client
    config: Config
    db: mogidb.Client

    container: VoteContainer = VoteContainer()

    message: discord.Message | None = None
    event: Event
    initial_players: list[str]
    formats: list[VoteEntry]
    votes_needed: int

    selected_format: EventFormat | None = None
    timeout_time: datetime

    def __init__(
        self,
        client: discord.Client,
        config: Config,
        db: mogidb.Client,
        event: Event,
        *,
        timeout: float = 120,
        flavor: str | None = None,
        votes_needed: int = 4,
    ):
        super().__init__(timeout=timeout)
        self.client = client
        self.config = config
        self.db = db
        self.flavor_text = flavor

        self.message = None
        self.event = event
        self.votes_needed = votes_needed
        self.formats = []

        # Retain inital player list
        self.initial_players = [p.user.id for p in event.players]

        self.timeout_time = datetime.now(UTC) + timedelta(seconds=timeout)

        if not event.room:
            raise ValueError("Expected event to have rooms embedded.")

        for _, format in enumerate(event.room.formats or []):
            view = VoteEntry(self.client, self.db, format, self.vote, votes_needed=self.votes_needed)
            self.formats.append(view)
            self.container.add_item(view)

    def allowed_mentions(self) -> AllowedMentions:
        allowed_mentions = AllowedMentions.none()
        allowed_mentions.users = [discord.Object(p.user.discord_user_id) for p in self.event.players if p.user.discord_user_id]
        return allowed_mentions

    async def update(self) -> None:
        header = ""
        for i, participant in enumerate(self.event.players):
            user = participant.user

            mention = f"@{user.display_name}"
            if user.discord_user_id is not None:
                discord_user = self.client.get_user(user.discord_user_id)
                if discord_user is None:
                    discord_user = await self.client.fetch_user(user.discord_user_id)

                mention = discord_user.mention

            if i > 0:
                # Add a space between mentions to make it more readable.
                header += f" {mention}"
            else:
                header += f"{mention}"

        if self.flavor_text is not None:
            header += f"\n{self.flavor_text}"

        if self.selected_format is None:
            header += (
                f"\n\nMogi has gathered. Vote for a format."
                f"\nVoting ends when a format gets 4 votes, or <t:{math.trunc(self.timeout_time.timestamp())}:R>"
            )
        else:
            header += (
                f"\n\nMogi has gathered."
                f"\nVoting concluded. **Format __{self.selected_format.name}__ selected!**"
            )

        # update container
        self.container.header.content = header

        for format in self.formats:
            await format.update()

    async def close_vote(self) -> None:
        """
        Closes the vote.

        This also calls `stop` to disable further interactions.
        """

        assert self.event.room
        assert self.event.room.guild

        room = self.event.room
        guild = self.event.room.guild

        votes = [v for v in self.formats]

        # Coin flip any ties
        random.shuffle(votes)
        votes.sort(key=lambda v: len(v.votes), reverse=True)

        format_id = votes[0].format.id
        # Refetch the selected format in case it went stale
        self.selected_format = await self.db.get_event_format(guild.id, room.id, format_id)
        assert self.selected_format, "Format should still exist"

        for format in self.formats:
            format.disabled = True
            format.anonymized = False

        await self.update()

        if not self.is_finished():
            self.stop()

        # Pull the event down again in case it was updated during voting
        self.event = await self.db.get_event(guild.id, room.id, self.event.id) or self.event

        # Get servers
        if isinstance(self.selected_format.servers, Unset):
            # "Silently" fetch the format
            logger.info(f"Fetching format {self.selected_format.name} from server...")
            self.selected_format = await self.db.get_event_format(guild.id, room.id, self.selected_format.id) or self.selected_format

        assert not isinstance(self.selected_format.servers, Unset)

        server = None
        if len(self.selected_format.servers) > 0:
            server = self.selected_format.servers.pop()

        # Update event
        self.event = await self.db.update_event(
            guild.id,
            room.id,
            self.event.id,
            format=format_id,
            server=server.id if server is not None else None,
        )

        # Assign teams using initial player list
        self.event = await self.db.assign_teams(guild.id, room.id, self.event.id, players=self.initial_players)

        # Update the message
        if self.message is not None:
            await self.message.edit(allowed_mentions=self.allowed_mentions(), view=self)

            # Send new view
            view = QueueStatus(self.config, self.client, self.db, self.event)
            assert isinstance(self.message.channel, discord.TextChannel)

            await view.update()
            if view.has_realtime:
                view.realtime()

            view.message = await self.message.channel.send(
                view=view,
                allowed_mentions=AllowedMentions.none()
            )

    async def on_timeout(self) -> None:
        await self.close_vote()

    async def vote(self, interaction: discord.Interaction, format: EventFormat):
        assert self.event.room
        assert self.event.room.guild

        should_close = False

        name = interaction.user.global_name

        # Refetch event
        self.event = (
            await self.db.get_event(self.event.room.guild.id, self.event.room.id, self.event.id)
            or self.event
        )

        try:
            player = next(p for p in self.event.players if p.user.discord_user_id == interaction.user.id)
        except StopIteration:
            # Player is not in the queue. Tell them to bug off.
            await interaction.response.send_message(
                f"{name}, you are not in the queue.",
                ephemeral=True
            )
            return

        # Check if the player is a sub
        if player.substitute:
            await interaction.followup.send(
                f"Sorry {name}, subs may not vote on formats!",
                ephemeral=True
            )
            return

        # Do nothing if the vote is closed.
        # Do nothing if this user isn't part of the mogi's starting selection
        if self.selected_format is None:
            # Remove user from other votes
            for entry in self.formats:
                old_len = len(entry.votes)
                entry.votes = [
                    u for u in entry.votes if u.discord_user_id != interaction.user.id
                ]

                # Only regenerate label if
                if len(entry.votes) != old_len:
                    await entry.update()

            entry = next(v for v in self.formats if v.format == format)

            user = await self.db.upsert_user(
                interaction.user.id,
                interaction.user.global_name or interaction.user.name
            )
            entry.votes.append(user)

            await entry.update()

            if len(entry.votes) >= self.votes_needed:
                should_close = True

        if should_close:
            await self.close_vote()

        # Redisplay modal
        await interaction.response.edit_message(
            allowed_mentions=self.allowed_mentions(), view=self
        )
