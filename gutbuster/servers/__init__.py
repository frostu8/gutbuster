from .server import Server, ConnectError
from .packet import (
    ServerInfo,
    PacketError,
    Packet,
    ServerFlags,
    RefuseReason,
    GameSpeed,
)
from .watcher import ServerWatcher, WatchedServer
from gutbuster.app import GroupModule
from gutbuster.config import Config
import discord
import asyncio
import math
from copy import copy
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.exc import IntegrityError
from discord import app_commands, ui
from discord.ext import tasks
from discord.ui.separator import SeparatorSpacing
from typing import Optional, List

__all__ = [
    "Server",
    "ServerInfo",
    "ServerWatcher",
    "WatchedServer",
    "Packet",
    "PacketError",
    "ConnectError",
    "GameSpeed",
    "RefuseReason",
    "ServerFlags",
]


class ServerContainer(ui.Container):
    server: WatchedServer
    header: ui.TextDisplay

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

            self.header = ui.TextDisplay(content)
            self.add_item(self.header)
        else:
            # Generate content
            content = ""
            if self.server.label is not None:
                content += f"## {self.server.label}\n"

            content += f"🟢 **IP** `{self.server.ip}:{self.server.port}`"
            self.header = ui.TextDisplay(content)

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


class ServersView(ui.LayoutView):
    message: Optional[discord.Message]
    containers: List[ServerContainer]

    def __init__(self, config: Config, *servers: WatchedServer, timeout: Optional[int | float] = 1800):
        super().__init__(timeout=timeout)

        self.message = None
        self.containers = []
        for server in servers:
            container = ServerContainer(config, server)
            self.containers.append(container)
            self.add_item(container)

    async def _realtime(self) -> None:
        while True:
            futures = (container._wait_until_update() for container in self.containers)
            await next(asyncio.as_completed(futures))

            # Update message
            if self.message is not None:
                await self.message.edit(view=self)

    def realtime(self) -> None:
        """
        Updates the embed in real-time for the duration of the view's
        existence.
        """

        self._task = asyncio.create_task(self._realtime())

    async def on_timeout(self) -> None:
        if self._task is not None:
            self._task.cancel()


class ServersModule(
    GroupModule,
    name="servers",
    description="Ring Racers server management commands",
    default_permissions=discord.Permissions.none(),
):
    config: Config
    db: AsyncEngine
    watcher: ServerWatcher

    command: Optional[app_commands.AppCommand]

    def __init__(self, config: Config, db: AsyncEngine, watcher: ServerWatcher):
        self.config = config
        self.db = db
        self.watcher = watcher

        self.command = None

    async def on_setup(self, tree: app_commands.CommandTree):
        commands = await tree.fetch_commands()
        self.command = next(c for c in commands if c.name == "servers")

        # Start watching servers
        await self.watcher.load()
        self.knock_servers.start()

    @app_commands.command(name="add", description="Adds a server to Gutbuster")
    @app_commands.describe(ip="The ip of the server")
    @app_commands.describe(label="A user-friendly name to describe the server")
    async def servers_add(
        self, interaction: discord.Interaction, ip: str, label: Optional[str]
    ):
        """
        The /servers add command.
        """

        if interaction.guild is None:
            # Ignore any user commands
            raise ValueError("Command not being called in a guild context?")

        server = await self.watcher.add(interaction.guild, remote=ip, label=label)

        # Ack the command, because knocking may take a while
        await interaction.response.defer(thinking=True)

        # Knock
        try:
            await server.knock()
        except PacketError:
            # Do nothing on packet errors
            pass
        except ConnectError:
            # Do nothing on connect errors
            pass

        # Update label if the user passed no label
        if server.server_name is not None:
            async with self.db.connect() as conn:
                try:
                    await server.update_label(server.server_name, conn)
                    await conn.commit()
                except IntegrityError:
                    pass

        view = ServersView(self.config, server)
        view.message = await interaction.followup.send(view=view)
        view.realtime()

    @app_commands.command(name="remove", description="Removes a server from Gutbuster")
    @app_commands.describe(ip_or_label="The ip of the server, or the server's label")
    async def servers_remove(
        self, interaction: discord.Interaction, ip_or_label: str
    ):
        """
        The /servers remove command.
        """

        if interaction.guild is None:
            # Ignore any user commands
            raise ValueError("Command not being called in a guild context?")

        to_remove = set()
        for server in self.watcher.iter(interaction.guild):
            # Check canonical name
            if server.remote == ip_or_label:
                to_remove.add(server)

            # Check IP name
            ip = f"{server.ip}:{server.port}"
            if ip == ip_or_label:
                to_remove.add(server)

            # /remove removes one matched label or many ip matches
            if server.label == ip_or_label:
                to_remove.clear()
                to_remove.add(server)
                break

        for server in to_remove:
            await self.watcher.remove(server)

        await interaction.response.send_message(
            f"Removed {len(to_remove)} {'server' if len(to_remove) == 1 else 'servers'}"
        )

    @app_commands.command(
        name="list", description="Lists all servers Gutbuster has registered"
    )
    async def servers_list(self, interaction: discord.Interaction):
        """
        The /servers list command.
        """

        if interaction.guild is None:
            # Ignore any user commands
            raise ValueError("Command not being called in a guild context?")

        if self.command is None:
            raise ValueError("Command being called before init")

        # Ack the command, because knocking may take a while
        await interaction.response.defer(thinking=True)

        servers = []

        for server in self.watcher.iter(interaction.guild):
            # await server.knock()
            servers.append(server)

        if len(servers) > 0:
            view = ServersView(self.config, *servers)
            view.message = await interaction.followup.send(view=view)
            view.realtime()
        else:
            await interaction.followup.send(
                "No servers added!\n"
                f"Get this party started by adding a server w/ </servers add:{self.command.id}>"
            )

    @tasks.loop(seconds=30.0)
    async def knock_servers(self) -> None:
        for server in self.watcher.iter():
            await server.knock()
