from gutbuster.servers.watcher import ServerWatcher
from sqlalchemy.ext.asyncio import AsyncEngine
from gutbuster.model.guild import PersistentStatus
from asyncio import Task
import discord
from copy import copy
import math
from datetime import datetime, timezone
from gutbuster.servers.packet import GameSpeed
from typing import Optional, List
from discord import ui, SeparatorSpacing
from gutbuster.servers import WatchedServer
from bot.config import Config
import asyncio

class ServerContainer(ui.Container):
    server: WatchedServer
    header: ui.TextDisplay = ui.TextDisplay(content="")

    _task: Optional[asyncio.Task]

    def __init__(self, config: Config, server: WatchedServer):
        self.server = server
        self._task = None

        if self.server.info is None:
            color = config.colors.server_offline
        elif self.server.info.gametype_name == "Race":
            color = config.colors.server_online_race
        elif self.server.info.gametype_name == "Battle":
            color = config.colors.server_online_battle
        else:
            color = config.colors.server_online_custom

        super().__init__(accent_color=color)
        self.regenerate()

    async def _wait_until_update(self) -> None:
        await self.server.update_event.wait()
        self.regenerate()

    def regenerate(self) -> None:
        """
        Regenerates the embed.
        """

        self.clear_items()

        # TODO: Figure out a workaround for Discord having "security"
        _join_url = f"ringracers://{self.server.ip}:{self.server.port}"

        if self.server.info is None:
            content = ""
            if self.server.label is not None:
                content += f"## {self.server.label}\n"

            content += "🔴 Server is offline."

            self.header.content = content
            self.add_item(self.header)
        else:
            # Generate content
            content = ""
            if self.server.label is not None:
                content += f"## {self.server.label}\n"

            content += f"🟢 **IP** `{self.server.ip}:{self.server.port}`"
            self.header.content = content

            self.add_item(self.header)
            self.add_item(ui.Separator(spacing=SeparatorSpacing.large))

            # Generate additional info
            game_speed = "2 Fast"
            match self.server.info.game_speed:
                case GameSpeed.EASY:
                    game_speed = "Gear 1"
                case GameSpeed.NORMAL:
                    game_speed = "Gear 2"
                case GameSpeed.HARD:
                    game_speed = "Gear 3"
                case _:
                    pass

            content = f"**Map** {self.server.map_title}\n**Game Speed** {game_speed}"

            if len(self.server.players) > 0:
                content += "\n\n**Players**"

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


class ServerView(ui.LayoutView):
    message: Optional[discord.Message]
    containers: List[ServerContainer]

    _task: Optional[Task[None]]

    def __init__(self, config: Config, *servers: WatchedServer, timeout: Optional[int | float] = 1800):
        super().__init__(timeout=timeout)

        self.message = None
        self.containers = []
        for server in servers:
            container = ServerContainer(config, server)
            self.containers.append(container)
            self.add_item(container)

        self._task = None

    def stop(self) -> None:
        if self._task is not None and not self._task.done:
            # Cancel task
            self._task.cancel()

    async def _realtime(self) -> None:
        while True:
            futures = (container._wait_until_update() for container in self.containers)
            await next(asyncio.as_completed(futures))

            # Update message
            if self.message is not None:
                try:
                    await self.message.edit(view=self)
                except discord.NotFound:
                    # Message was deleted, stop realtime
                    self.stop()

    def realtime(self) -> None:
        """
        Updates the embed in real-time for the duration of the view's
        existence.
        """

        if self._task is not None and not self._task.done:
            # Cancel task
            self._task.cancel()

        self._task = asyncio.create_task(self._realtime())

    async def on_timeout(self) -> None:
        if self._task is not None:
            self._task.cancel()


class PersistentServerView(ServerView):
    """
    A servers view that persists on restarts.
    """

    db: AsyncEngine
    watcher: ServerWatcher
    config: Config
    
    obj: PersistentStatus

    channel: Optional[discord.TextChannel]

    def __init__(self, obj: PersistentStatus, config: Config, watcher: ServerWatcher, db: AsyncEngine, timeout: Optional[int | float] = None):
        super().__init__(config, timeout=timeout)
        self.obj = obj
        self.config = config
        self.watcher = watcher
        self.db = db
        self.channel = None

    async def _fetch_channel(self, client: discord.Client) -> discord.TextChannel:
        channel = self.obj.channel
        if not isinstance(channel, discord.TextChannel):
            channel = client.get_channel(self.obj.channel.id)
        if not isinstance(channel, discord.TextChannel):
            channel = await client.fetch_channel(self.obj.channel.id)

        assert isinstance(channel, discord.TextChannel)
        self.channel = channel

        return channel

    async def send(self, client: discord.Client) -> None:
        channel = self.channel
        if channel is None:
            channel = await self._fetch_channel(client)

        if self.message is not None:
            await self.message.delete()

        self.message = await channel.send(view=self)
        async with self.db.connect() as conn:
            await self.obj.set_message(self.message, conn)
            await conn.commit()

    async def update(self) -> None:
        self.clear_items()
        self.containers.clear()
        for server in self.watcher.iter(self.obj.parent):
            container = ServerContainer(self.config, server)
            self.add_item(container)
            self.containers.append(container)

        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                # Message was deleted, stop realtime
                self.stop()

        # Restart realtime task
        if self._task is not None:
            self.realtime()
