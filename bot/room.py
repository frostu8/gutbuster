import discord
from discord import app_commands
from discord.app_commands import default_permissions

import mogidb
from bot.app import GroupModule, Module
from bot.ui.room import RoomConfigView
from mogidb.model import FormatSelectionMode, RoomOptions, TeamMode, UpdateRoomOptions


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


class RoomConfigModule(
    GroupModule,
    name = "config",
    description = "Fetch and apply bot configuration",
    default_permissions=discord.Permissions.none(),
):
    db: mogidb.Client

    command_enable: app_commands.AppCommand | None

    def __init__(self, db: mogidb.Client):
        self.db = db
        self.command_enable = None

    async def on_setup(self, tree: app_commands.CommandTree):
        commands = await tree.fetch_commands()
        self.command_enable = next(c for c in commands if c.name == "enable")

    @app_commands.command(name="show", description="Shows the current config of the room")
    async def show(self, interaction: discord.Interaction) -> None:
        """
        The /config show command.

        Shows channel configuration.
        """

        assert interaction.guild
        assert self.command_enable

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "This channel cannot be used to run mogis!",
            )
            return

        # Get or create guild
        guild = await self.db.get_guild(interaction.guild.id)
        if guild is None:
            guild = await self.db.create_guild(interaction.guild.id)

        # Fetch room, and check if it's enabled
        room = await self.db.get_room(guild.id, interaction.channel.id)
        if room is None or not room.enabled:
            await interaction.response.send_message(
                "This channel has not been enabled."
                f" Try {self.command_enable.mention}ing the channel first.",
            )
            return

        # Build up the config embed
        view = RoomConfigView(interaction.channel, room)
        await interaction.response.send_message(view=view, ephemeral=True)

    @app_commands.command(name="set", description="Sets configuration options")
    @app_commands.describe(decay_after="How long it takes for a queue to decay")
    @app_commands.describe(inactivity_warning_after="Time before a queued player is warned for inactivity")
    @app_commands.describe(inactivity_drop_after="Time before a queued player is dropped for inactivity")
    @app_commands.describe(players_required="The players required to start a queue")
    @app_commands.describe(max_players="The maximum number of players in a queue, including subs")
    @app_commands.describe(format_selection_mode="The method of format selection")
    @app_commands.describe(votes_required="The amount of votes needed to end the vote early")
    async def set_config(
        self,
        interaction: discord.Interaction,
        decay_after: int | None,
        inactivity_warning_after: int | None,
        inactivity_drop_after: int | None,
        players_required: int | None,
        max_players: int | None,
        format_selection_mode: FormatSelectionMode | None,
        votes_required: int | None,
    ) -> None:
        """
        The /config set command.

        Updates channel configuration.
        """

        assert interaction.guild
        assert self.command_enable

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "This channel cannot be used to run mogis!",
            )
            return

        # Get or create guild
        guild = await self.db.get_guild(interaction.guild.id)
        if guild is None:
            guild = await self.db.create_guild(interaction.guild.id)

        # Fetch room, and check if it's enabled
        room = await self.db.get_room(guild.id, interaction.channel.id)
        if room is None or not room.enabled:
            await interaction.response.send_message(
                "This channel has not been enabled."
                f" Try {self.command_enable.mention}ing the channel first.",
            )
            return

        # Apply config options
        room = await self.db.update_room(
            guild.id,
            room.id,
            options=UpdateRoomOptions(
                decay_after=decay_after,
                inactivity_warning_after=inactivity_warning_after,
                inactivity_drop_after=inactivity_drop_after,
                players_required=players_required,
                max_players=max_players,
                format_selection_mode=format_selection_mode,
                votes_required=votes_required,
            ),
        )

        # Build up the config embed
        view = RoomConfigView(interaction.channel, room)
        await interaction.response.send_message(view=view, ephemeral=True)
