import math
from datetime import datetime, timezone
from copy import copy
from gutbuster.config import Config
import asyncio
from asyncio import Task
from discord import ui, AllowedMentions, SeparatorSpacing
from typing import Optional
import discord
from gutbuster.servers import WatchedServer, ServerWatcher, GameSpeed
from gutbuster.model import Event


class QueueStatusContainer(ui.Container):
    """
    The discord container.
    """

    config: Config
    event: Event
    server: Optional[WatchedServer]

    def __init__(self, config: Config, event: Event, *, server: Optional[WatchedServer] = None):
        super().__init__()
        self.config = config
        self.event = event
        self.server = server

    def color(self) -> discord.Color:
        """
        The accent color of the embed.
        """

        if self.server is None:
            return self.config.colors.server_offline

        if self.server.info is None:
            return self.config.colors.server_offline
        elif self.server.info.gametype_name == "Race":
            return self.config.colors.server_online_race
        elif self.server.info.gametype_name == "Battle":
            return self.config.colors.server_online_battle
        else:
            return self.config.colors.server_online_custom

    def regenerate(self) -> None:
        """
        Regenerates the embed.
        """

        self.clear_items()
        self.accent_color = self.color()

        if self.event.format is not None:
            content = f"Format __**{self.event.format.name}**__\n"
        else:
            content = ""

        # List participants
        # TODO: List team balancer results
        for i, participant in enumerate(self.event.get_participants()):
            mention = f"@{participant.user.name}"
            if isinstance(participant.user.user, discord.User | discord.Member):
                mention = participant.user.user.mention

            if i > 0:
                # Add a space between mentions to make it more readable.
                content += f" {mention}"
            else:
                content += f"{mention}"

        content += "\n\n"

        if self.server is None:
            # We're done, if there is no server information.
            self.add_item(ui.TextDisplay(content))
            return

        # Add the server label with the format selection.
        if self.server.label is not None:
            content += f"⚡🔌 Playing on **{self.server.label}**\n"

        if self.server.info is None:
            content += "🔴 Server is offline."
        else:
            content += f"🟢 **IP** `{self.server.ip}:{self.server.port}`"

        self.add_item(ui.TextDisplay(content))

        if self.server.info is not None:
            # Build the server information listing
            self.add_item(ui.Separator(spacing=SeparatorSpacing.large))

            # Show map title
            content = f"**Map** {self.server.map_title}\n"

            if len(self.server.players) > 0:
                # List all players
                players = copy(self.server.players)
                players.sort(key=lambda a: a.score, reverse=True)
                for player in players:
                    score = str(player.score).rjust(4, " ")

                    if player.team == 255:
                        content += f"\n`{score}` *{player.name}*"
                    else:
                        content += f"\n`{score}` {player.name}"

            self.add_item(ui.TextDisplay(content))

        # Timestamp embed
        if self.server.last_updated is not None:
            epoch = datetime.fromtimestamp(0, timezone.utc)

            timestamp = math.trunc(
                (self.server.last_updated - epoch).total_seconds()
            )
            footer_content = f"Last updated at <t:{timestamp}:T>"

            self.add_item(ui.TextDisplay(footer_content))

    async def _wait_for_update(self) -> None:
        if self.server is None:
            raise ValueError("No server to update.")
        else:
            await self.server.update_event.wait()


class QueueStatus(ui.LayoutView):
    """
    A sticky message that reports status on the queues.
    """

    event: Event

    container: QueueStatusContainer

    client: discord.Client
    message: Optional[discord.Message]
    _task: Optional[Task[None]]

    def __init__(self, client: discord.Client, config: Config, event: Event, servers: ServerWatcher, *, timeout: Optional[int | float] = 60*60):
        super().__init__(timeout=timeout)
        self.event = event

        # Find server attached to event
        guild = discord.Object(id=event.room.discord_guild_id)
        try:
            server = next(filter(lambda s: s.remote == self.event.remote, servers.iter(guild)))
        except StopIteration:
            server = None

        self.container = QueueStatusContainer(config, event, server=server)
        self.add_item(self.container)

        self.client = client
        self.message = None
        self._task = None

    async def send(self, channel: discord.TextChannel):
        """
        Sends the status view into a channel.
        """

        # Cache all users
        for participant in self.container.event.get_participants():
            await participant.user.fetch_user(self.client)

        self.container.regenerate()
        self.message = await channel.send(view=self, allowed_mentions=AllowedMentions.none())
        if self.has_realtime():
            self.realtime()

    async def _realtime(self) -> None:
        while True:
            await self.container._wait_for_update()

            # Cache all users
            for participant in self.container.event.get_participants():
                await participant.user.fetch_user(self.client)

            self.container.regenerate()

            # Update message
            if self.message is not None:
                await self.message.edit(view=self, allowed_mentions=AllowedMentions.none())

    def has_realtime(self) -> bool:
        return self.container.server is not None

    def realtime(self) -> None:
        """
        Creates a task that refreshes the server listing periodically.
        """

        self._task = asyncio.create_task(self._realtime())

    async def on_timeout(self) -> None:
        if self._task is not None:
            self._task.cancel()
            
