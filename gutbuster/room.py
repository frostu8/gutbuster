import discord
from enum import Enum, unique
from discord import app_commands
from discord.app_commands import default_permissions
from sqlalchemy.ext.asyncio import AsyncEngine
from gutbuster.model import get_room, create_room
from gutbuster.app import Module, GroupModule


@unique
class ConfigOption(Enum):
    PLAYERS_REQUIRED = "players_required"


class RoomConfigModule(
    GroupModule,
    name="configure",
    description="Configures a channel's settings",
    default_permissions=None,
):
    db: AsyncEngine

    def __init__(self, db: AsyncEngine):
        self.db = db

    @app_commands.command(name="set", description="Sets a config option")
    async def set_option(self, interaction: discord.Interaction) -> None:
        pass


class RoomModule(Module):
    db: AsyncEngine

    def __init__(self, db: AsyncEngine):
        self.db = db

    @app_commands.command(name="enable", description="Enables the channel to run mogis")
    @default_permissions(None)
    async def enable(self, interaction: discord.Interaction) -> None:
        """
        The /enable command.

        Enables Mogis to take place in a channel.
        """

        if interaction.channel is None:
            # Ignore any user commands
            raise ValueError("Command not being called in a guild context?")

        async with self.db.connect() as conn:
            # Find the room
            room = await get_room(interaction.channel, conn)
            if room is None:
                # The admin wants to enable this channel!
                # Make the room, and then make a default FFA format.
                room = await create_room(interaction.channel, conn)
                await room.add_format("FFA", conn)

                await interaction.response.send_message(
                    f"Channel {interaction.channel.mention} has been enabled and initialized to run mogis.\nFormat `FFA` automatically added.",
                )
            else:
                if not room.enabled:
                    await room.enable(conn)

                await interaction.response.send_message(
                    f"Channel {interaction.channel.mention} has been enabled.",
                )

            await conn.commit()

    @app_commands.command(name="disable", description="Disables the channel")
    @default_permissions(None)
    async def disable(self, interaction: discord.Interaction) -> None:
        """
        The /disable command.

        Disables the channel's ability to run Mogis.
        """

        if interaction.channel is None:
            # Ignore any user commands
            raise ValueError("Command not being called in a guild context?")

        async with self.db.connect() as conn:
            # Find the room
            room = await get_room(interaction.channel, conn)
            if room is not None and room.enabled:
                # Disable the room
                await room.disable(conn)

            await interaction.response.send_message(
                f"Channel {interaction.channel.mention} has been disabled.",
            )

            await conn.commit()
