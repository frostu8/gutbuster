import asyncio
import math
from asyncio import Task
from copy import copy
from datetime import UTC, datetime

import discord
from discord import SeparatorSpacing, ui
from sqlalchemy.ext.asyncio import AsyncEngine

import mogidb
from bot.boards import PersistentStatus
from bot.config import Config
from mogidb.model import GameServer, GameSpeed, Guild


class ServerContainer(ui.Container):
    server: GameServer
    header: ui.TextDisplay = ui.TextDisplay(content="")

    _task: asyncio.Task | None

    def __init__(self, config: Config, server: GameServer):
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

    def regenerate(self) -> None:
        """
        Regenerates the embed.
        """

        self.clear_items()

        # TODO: Figure out a workaround for Discord having "security"
        _join_url = f"ringracers://{self.server.remote}"

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

            content += f"🟢 **IP** `{self.server.remote}`"
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

            content = f"**Map** {self.server.info.map_name}\n**Game Speed** {game_speed}"

            if len(self.server.info.players) > 0:
                content += "\n\n**Players**"

                # List all players
                players = copy(self.server.info.players)
                players.sort(key=lambda a: a.score, reverse=True)
                for player in players:
                    score = str(player.score).rjust(4, " ")

                    if player.team == 255:
                        content += f"\n`{score}` *{player.name}*"
                    else:
                        content += f"\n`{score}` {player.name}"

            self.add_item(ui.TextDisplay(content))

            # Timestamp embed
            if self.server.last_update_time is not None:
                epoch = datetime.fromtimestamp(0, UTC)

                timestamp = math.trunc(
                    (self.server.last_update_time - epoch).total_seconds()
                )
                footer_content = f"Last updated at <t:{timestamp}:T>"

                self.add_item(ui.TextDisplay(footer_content))


class ServerView(ui.LayoutView):
    message: discord.Message | None
    containers: list[ServerContainer]
    guild: Guild

    config: Config
    db: mogidb.Client

    _task: Task[None] | None

    def __init__(self, config: Config, db: mogidb.Client, guild: Guild, *servers: GameServer, timeout: float | None = 1800):
        super().__init__(timeout=timeout)

        self.config = config
        self.db = db

        self.guild = guild
        self.message = None
        self.containers = []
        for server in servers:
            container = ServerContainer(config, server)
            self.containers.append(container)
            self.add_item(container)

        self._task = None

    def stop(self) -> None:
        super().stop()

        if self._task is not None and not self._task.done():
            # Cancel task
            self._task.cancel()

    async def _realtime(self) -> None:
        while True:
            # Sleep until poking API again
            await asyncio.sleep(30)

            # POKE API!!!!!!!!!!!!!
            should_update = False
            for container in self.containers:
                server = await self.db.get_server(self.guild.id, container.server.id)
                if server is not None:
                    container.server = server
                    container.regenerate()
                    should_update = True

            # Update message
            if should_update and self.message is not None:
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

        if self._task is not None and not self._task.done():
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

    sqldb: AsyncEngine
    obj: PersistentStatus

    channel: discord.TextChannel | None

    def __init__(self, obj: PersistentStatus, config: Config, db: mogidb.Client, sqldb: AsyncEngine, timeout: float | None = None):
        super().__init__(config, db, obj.guild, timeout=timeout)
        self.sqldb = sqldb
        self.obj = obj

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
        async with self.sqldb.connect() as conn:
            await self.obj.set_message(self.message, conn)
            await conn.commit()

    async def update(self) -> None:
        is_realtime = False
        if self._task is not None and not self._task.done():
            # Cancel task
            self._task.cancel()
            is_realtime = True

        self.clear_items()
        self.containers.clear()

        # Fetch servers from MogiDB
        servers = await self.db.list_servers(self.guild.id)
        for server in servers:
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
        if is_realtime:
            self.realtime()
