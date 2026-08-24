import logging

import discord
from discord import app_commands
from sqlalchemy.ext.asyncio import AsyncEngine

import mogidb
from bot.app import GroupModule
from bot.boards import create_board, list_all_boards
from bot.config import Config
from bot.ui.server import PersistentServerView, ServerView
from mogidb import Unset
from mogidb.model import Guild

logger = logging.getLogger(__name__)


class ServerModule(
    GroupModule,
    name="servers",
    description="Ring Racers server management commands",
    default_permissions=discord.Permissions.none(),
):
    config: Config
    sqldb: AsyncEngine
    db: mogidb.Client
    client: discord.Client

    pinned_views: list[PersistentServerView]

    command: app_commands.AppCommand | None

    def __init__(self, config: Config, db: mogidb.Client, sqldb: AsyncEngine, client: discord.Client):
        self.config = config
        self.db = db
        self.sqldb = sqldb
        self.client = client

        self.pinned_views = []

        self.command = None

    async def on_setup(self, tree: app_commands.CommandTree):
        commands = await tree.fetch_commands()
        self.command = next(c for c in commands if c.name == "servers")

    async def on_ready(self):
        # Register pinned views
        async with self.sqldb.connect() as conn:
            pinned = await list_all_boards(self.db, conn)

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
                    self.db,
                    self.sqldb,
                )
                view.message = message
                view.channel = channel
                self.pinned_views.append(view)

            await conn.commit()

        for view in self.pinned_views:
            await view.update()
            view.realtime()

    @app_commands.command(name="add", description="Adds a server to Gutbuster")
    @app_commands.describe(ip="The ip of the server")
    @app_commands.describe(label="A user-friendly name to describe the server")
    async def servers_add(
        self, interaction: discord.Interaction, ip: str, label: str | None
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
        guild = await self.db.get_guild(interaction.guild.id)
        if guild is None:
            guild = await self.db.create_guild(interaction.guild.id)

        # Register to server to MogiDB, allow the API to knock on our behalf
        server = await self.db.create_server(
            interaction.guild.id,
            remote=ip,
            label=label
        )

        view = ServerView(self.config, self.db, guild, server)
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
        guild = await self.db.get_guild(interaction.guild.id)
        if guild is None:
            guild = await self.db.create_guild(interaction.guild.id)

        assert not isinstance(guild.servers, Unset)

        to_remove = set()
        for server in guild.servers:
            # Check canonical name
            if server.remote == ip_or_label:
                to_remove.add(server)

            # Check IP name
            # NOTE: MogiDB only presents canonical names, but this might come
            # back later
            # ip = f"{server.ip}:{server.port}"
            # if ip == ip_or_label:
            #     to_remove.add(server)

            # /remove removes one matched label or many ip matches
            if server.label == ip_or_label:
                to_remove.clear()
                to_remove.add(server)
                break

        for server in to_remove:
            await self.db.delete_server(guild.id, server.id)

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
        guild = await self.db.get_guild(interaction.guild.id)
        if guild is None:
            guild = await self.db.create_guild(interaction.guild.id)

        assert not isinstance(guild.servers, Unset)

        if len(guild.servers) == 0:
            await interaction.response.send_message(
                "No servers added!\n"
                f"Get this party started by adding a server w/ </servers add:{self.command.id}>"
            )
            return

        view = ServerView(self.config, self.db, guild, *guild.servers)
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
        guild = await self.db.get_guild(interaction.guild.id)
        if guild is None:
            guild = await self.db.create_guild(interaction.guild.id)

        assert not isinstance(guild.servers, Unset)

        # Create new guild if we need to
        async with self.sqldb.connect() as conn:
            # Do we really need to fetch the board list???
            #boards = await list_boards(guild, conn)

            if len(guild.servers) == 0:
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
                obj = await create_board(guild, channel, conn)
                await conn.commit()
                view = PersistentServerView(obj, self.config, self.db, self.sqldb)

            await view.update()
            await view.send(interaction.client)
            view.realtime()

        await interaction.response.send_message(
            "Persistent board created.\nTo remove the board, just delete the message.",
            ephemeral=True,
        )

    async def update_persistent(self, guild: Guild) -> None:
        for view in self.pinned_views:
            if view.obj.guild.id == guild.id:
                await view.update()
