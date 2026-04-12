from gutbuster.sticky import StickyServer
from gutbuster.servers import ServerWatcher
from gutbuster.config import Config
import random
import math
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncEngine
from typing import Callable, Awaitable, Any, List, Optional
from gutbuster.model import EventFormat, User, Event, get_event, get_user
from discord import ui, ButtonStyle, AllowedMentions
import discord
from .queue import QueueStatus


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
    db: AsyncEngine

    format: EventFormat
    votes: List[User]

    anonymized: bool
    quality: float
    votes_needed: int

    _disabled: bool

    def __init__(
        self,
        client: discord.Client,
        db: AsyncEngine,
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

        self.regenerate()

    @property
    def disabled(self):
        return self._disabled

    @disabled.setter
    def disabled(self, value: bool):
        self._disabled = value

        if isinstance(self.accessory, VoteButton):
            self.accessory.disabled = self._disabled

    def regenerate(self):
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

    client: discord.Client
    config: Config
    watcher: ServerWatcher
    db: AsyncEngine
    sticky_server: StickyServer

    container: VoteContainer = VoteContainer()

    message: Optional[discord.Message] = None
    event: Event
    formats: List[VoteEntry] = []
    votes_needed: int

    selected_format: Optional[EventFormat] = None
    timeout_time: datetime

    def __init__(
        self,
        client: discord.Client,
        config: Config,
        watcher: ServerWatcher,
        db: AsyncEngine,
        sticky_server: StickyServer,
        event: Event,
        *,
        timeout: int | float = 120.0,
        flavor: Optional[str] = None,
        votes_needed: int = 4,
    ):
        super().__init__(timeout=timeout)
        self.client = client
        self.config = config
        self.watcher = watcher
        self.db = db
        self.sticky_server = sticky_server
        self.flavor_text = flavor

        self.message = None
        self.event = event
        self.votes_needed = votes_needed

        self.timeout_time = datetime.now() + timedelta(seconds=timeout)

        for _, format in enumerate(event.room.formats):
            view = VoteEntry(self.client, self.db, format, self.vote, votes_needed=self.votes_needed)
            self.formats.append(view)
            self.container.add_item(view)

        self.update_header()

    def allowed_mentions(self) -> AllowedMentions:
        allowed_mentions = AllowedMentions.none()
        allowed_mentions.users = [p.user.user for p in self.event.get_participants()]
        return allowed_mentions
        # return AllowedMentions.none()

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
                f"\n\nMogi has gathered. Vote for a format."
                f"\nVoting ends when a format gets 4 votes, or <t:{math.trunc(self.timeout_time.timestamp())}:R>"
            )
        else:
            header += (
                f"\n\nMogi has gathered."
                f"\nVoting concluded. **Format {self.selected_format.name} selected!**"
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

            # Find server for queue
            server = await self.selected_format.find_server(conn)
            if server is not None:
                await self.event.set_remote(server.remote, conn)

            await conn.commit()

        # Update the message
        if self.message is not None:
            await self.message.edit(allowed_mentions=self.allowed_mentions(), view=self)

            # Send new view
            sticky = QueueStatus(self.client, self.db, self.config, self.event, self.watcher)
            assert isinstance(self.message.channel, discord.TextChannel)
            self.sticky_server.stick(self.message.channel, view=sticky, allowed_mentions=AllowedMentions.none())

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
