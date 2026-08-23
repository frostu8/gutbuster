import discord
from discord import app_commands
from discord.app_commands import default_permissions

import mogidb
from bot.app import Module
from mogidb.model import TeamMode


class RoomModule(Module):
    db: mogidb.Client

    def __init__(self, db: mogidb.Client):
        self.db = db

    @app_commands.command(name="enable", description="Enables the channel to run mogis")
    @default_permissions(None)
    async def enable(self, interaction: discord.Interaction) -> None:
        """
        The /enable command.

        Enables Mogis to take place in a channel.
        """

        assert interaction.guild

        # Get channel name
        if isinstance(interaction.channel, discord.TextChannel):
            channel_name = interaction.channel.name
        else:
            await interaction.response.send_message(
                "This channel cannot be used to run mogis!",
            )
            return

        # Get or create guild
        guild = await self.db.get_guild(interaction.guild.id)
        if guild is None:
            guild = await self.db.create_guild(interaction.guild.id)

        # Get the room
        room = await self.db.get_room(guild.id, interaction.channel.id)
        if room is None:
            # The admin wants to enable this channel!
            # Make the room, and then make a default FFA format.
            room = await self.db.create_room(
                guild.id,
                interaction.channel.id,
                channel_name,
                # AHHH !!! FUCK!! WHY ISN'T IT ENABLED BY DEFAULT!!!
                enabled=True,
            )
            await self.db.create_event_format(guild.id, room.id, "FFA", TeamMode.FFA)

            await interaction.response.send_message(
                f"Channel {interaction.channel.mention} has been enabled and initialized to run mogis.\nFormat `FFA` automatically added.",
            )
        else:
            if not room.enabled:
                await self.db.update_room(guild.id, room.id, enabled=True)

            await interaction.response.send_message(
                f"Channel {interaction.channel.mention} has been enabled.",
            )

    @app_commands.command(name="disable", description="Disables the channel")
    @default_permissions(None)
    async def disable(self, interaction: discord.Interaction) -> None:
        """
        The /disable command.

        Disables the channel's ability to run Mogis.
        """

        assert interaction.guild

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "This channel cannot be used to run mogis!",
            )
            return

        # Get or create guild
        guild = await self.db.get_guild(interaction.guild.id)
        if guild is None:
            guild = await self.db.create_guild(interaction.guild.id)

        # Get the room
        room = await self.db.get_room(guild.id, interaction.channel.id)
        if room is not None and room.enabled:
            await self.db.update_room(guild.id, room.id, enabled=False)

        await interaction.response.send_message(
            f"Channel {interaction.channel.mention} has been disabled.",
        )
