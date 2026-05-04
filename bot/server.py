from gutbuster.model import get_guild, create_guild, list_all_boards
from gutbuster.model.guild import Guild
from asyncio import Task
from gutbuster.servers import (
    Server,
    ConnectError,
    ServerInfo,
    PacketError,
    Packet,
    ServerFlags,
    RefuseReason,
    GameSpeed,
    ServerWatcher,
    WatchedServer
)
import discord
import asyncio
import math
import logging
from copy import copy
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.exc import IntegrityError
from discord import app_commands, ui
from discord.ext import tasks
from discord.ui.separator import SeparatorSpacing
from typing import Optional, List, Dict
from bot.app import GroupModule, Module
from bot.config import Config
from bot.ui.server import ServerView, PersistentServerView

logger = logging.getLogger(__name__)


class ServerModule(
    GroupModule,
    name="servers",
    description="Ring Racers server management commands",
    default_permissions=discord.Permissions.none(),
):
    config: Config
    db: AsyncEngine
    watcher: ServerWatcher
    client: discord.Client

    pinned_views: List[PersistentServerView]

    command: Optional[app_commands.AppCommand]

    def __init__(self, config: Config, db: AsyncEngine, watcher: ServerWatcher, client: discord.Client):
        self.config = config
        self.db = db
        self.watcher = watcher
        self.client = client

        self.pinned_views = []

        self.command = None

    async def on_setup(self, tree: app_commands.CommandTree):
        commands = await tree.fetch_commands()
        self.command = next(c for c in commands if c.name == "servers")

        # Start watching servers
        await self.watcher.load()
        self.knock_servers.start()

    async def on_ready(self):
        # Register pinned views
        async with self.db.connect() as conn:
            pinned = await list_all_boards(conn)

            for pin in pinned:
                if pin.message is None:
                    # Dangling board? remove it.
                    await pin.delete(conn)
                    continue

                # Fetch message
                channel = pin.channel
                if not isinstance(channel, discord.TextChannel):
                    channel = self.client.get_channel(pin.channel.id)
                if not isinstance(channel, discord.TextChannel):
                    channel = await self.client.fetch_channel(pin.channel.id)
                if not isinstance(channel, discord.TextChannel):
                    # The channel was deleted.
                    await pin.delete(conn)
                    continue

                pin.channel = channel

                try:
                    message = await channel.fetch_message(pin.message.id)
                except discord.NotFound:
                    # The message was deleted.
                    await pin.delete(conn)
                    continue

                pin.message = message

                view = PersistentServerView(
                    pin,
                    self.config,
                    self.watcher,
                    self.db,
                )
                view.message = message
                view.channel = channel
                await view.update()
                view.realtime()

                self.pinned_views.append(view)

            await conn.commit()

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

        # Ack the command, because knocking may take a while
        await interaction.response.defer(thinking=True)

        # Create new guild if we need to
        async with self.db.connect() as conn:
            guild = await get_guild(interaction.guild, conn)
            if guild is None:
                guild = await create_guild(interaction.guild, conn)

            await conn.commit()

        server = await self.watcher.add(guild, remote=ip, label=label)

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
                    await server.set_label(server.server_name, conn)
                    await conn.commit()
                except IntegrityError:
                    pass

        view = ServerView(self.config, server)
        view.message = await interaction.followup.send(view=view)
        view.realtime()

        # Update persistent views
        await self.update_persistent(guild)

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

        # Create new guild if we need to
        async with self.db.connect() as conn:
            guild = await get_guild(interaction.guild, conn)
            if guild is None:
                guild = await create_guild(interaction.guild, conn)

            await conn.commit()

        to_remove = set()
        for server in self.watcher.iter(guild):
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

        # Update persistent views
        await self.update_persistent(guild)

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

        assert self.command

        if interaction.guild is None:
            # Ignore any user commands
            raise ValueError("Command not being called in a guild context?")

        # Create new guild if we need to
        async with self.db.connect() as conn:
            guild = await get_guild(interaction.guild, conn)
            if guild is None:
                guild = await create_guild(interaction.guild, conn)

            await conn.commit()

        servers = []
        for server in self.watcher.iter(guild):
            servers.append(server)

        if len(servers) == 0:
            await interaction.response.send_message(
                "No servers added!\n"
                f"Get this party started by adding a server w/ </servers add:{self.command.id}>"
            )
            return

        view = ServerView(self.config, *servers)
        view.message = (await interaction.response.send_message(view=view)).resource
        view.realtime()

    @app_commands.command(
        name="persist", description="Lists servers and makes the message persist"
    )
    async def servers_persist(self, interaction: discord.Interaction):
        """
        The /servers persist command.
        """

        assert self.command

        if interaction.guild is None:
            # Ignore any user commands
            raise ValueError("Command not being called in a guild context?")

        channel = interaction.channel
        assert isinstance(channel, discord.TextChannel)

        # Create new guild if we need to
        async with self.db.connect() as conn:
            guild = await get_guild(interaction.guild, conn)
            if guild is None:
                guild = await create_guild(interaction.guild, conn)

            await conn.commit()
            await guild.preload_boards(conn)

            servers = []
            for server in self.watcher.iter(guild):
                servers.append(server)

            if len(servers) == 0:
                await interaction.response.send_message(
                    "No servers added!\n"
                    f"Get this party started by adding a server w/ </servers add:{self.command.id}>",
                    ephemeral=True
                )
                return

            # Check if there is already a pin
            view = next(filter(lambda v: v.obj.channel.id == channel.id, self.pinned_views), None)
            if view is None:
                # Create new pinned
                obj = await guild.add_board(channel, conn)
                await conn.commit()
                view = PersistentServerView(obj, self.config, self.watcher, self.db)

            view.update()
            await view.send(interaction.client)
            view.realtime()

        await interaction.response.send_message(
            "Persistent board created.\nTo remove the board, just delete the message.",
            ephemeral=True,
        )

    async def update_persistent(self, guild: Guild) -> None:
        for view in self.pinned_views:
            if view.obj.parent.id == guild.id:
                await view.update()

    @tasks.loop(seconds=30.0)
    async def knock_servers(self) -> None:
        for server in self.watcher.iter():
            try:
                await server.knock()
            except Exception as e:
                # Catch any exceptions
                logger.error(e)
