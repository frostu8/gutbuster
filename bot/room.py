from enum import IntEnum

import discord
from discord import AllowedMentions, app_commands
from discord.app_commands import Choice, default_permissions

import mogidb
from bot.app import GroupModule, Module
from bot.ui.room import (
    FormatDefaults,
    FormatModal,
    RoleBlacklistModal,
    RoleWhitelistModal,
    RoomConfigView,
)
from mogidb import ApiError, Unset
from mogidb.model import FormatSelectionMode, TeamMode, UpdateRoomOptions


class RoomModule(Module):
    db: mogidb.Client

    command_enable: app_commands.AppCommand | None

    def __init__(self, db: mogidb.Client):
        self.db = db

    async def on_setup(self, tree: app_commands.CommandTree):
        commands = await tree.fetch_commands()
        self.command_enable = next(c for c in commands if c.name == "enable")

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

        assert not isinstance(guild.servers, Unset)

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

            # let the ffa format use all the servers in the guild
            servers = [server.id for server in guild.servers]
            await self.db.create_event_format(guild.id, room.id, "FFA", TeamMode.FFA, servers)

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

    @app_commands.command(name="copy", description="Copies a channel config from another channel")
    @app_commands.rename(copy_from="from")
    @default_permissions(None)
    async def copy(
        self,
        interaction: discord.Interaction,
        copy_from: discord.TextChannel,
    ) -> None:
        """
        The /copy command.

        Copies a channel config from another channel
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

        # Get the room
        room = await self.db.get_room(guild.id, interaction.channel.id)
        if room is None or not room.enabled:
            await interaction.response.send_message(
                "This channel has not been enabled."
                f" Try {self.command_enable.mention}ing the channel first.",
            )
            return

        # Get the room to copy from
        copy_from_room = await self.db.get_room(guild.id, copy_from.id)
        if copy_from_room is None:
            await interaction.response.send_message(
                f"The channel {copy_from.mention} is not configured.",
            )
            return

        assert not isinstance(copy_from_room.formats, Unset)

        # First, copy config
        # TODO: probably a better way of doing this
        copy_options = copy_from_room.settings
        options = UpdateRoomOptions(
            decay_after = copy_options.decay_after,
            inactivity_warning_after = copy_options.inactivity_warning_after,
            inactivity_drop_after = copy_options.inactivity_drop_after,
            max_players = copy_options.max_players,
            players_required = copy_options.players_required,
            votes_required = copy_options.votes_required,
            format_selection_mode = copy_options.format_selection_mode,
        )

        # Push config updates
        room = await self.db.update_room(guild.id, room.id, options=options)
        assert not isinstance(room.formats, Unset)

        # Clear channel's current formats
        for format in room.formats:
            await self.db.delete_event_format(guild.id, room.id, format.id)

        room.formats.clear()

        # Copy formats
        for format in copy_from_room.formats:
            assert not isinstance(format.servers, Unset)

            new_format = await self.db.create_event_format(
                guild.id,
                room.id,
                name=format.name,
                team_mode=format.team_mode,
                servers=[server.id for server in format.servers]
            )
            room.formats.append(new_format)

        # Render new room
        view = RoomConfigView(interaction.channel, room)
        await interaction.response.send_message(
            view=view,
            allowed_mentions=AllowedMentions.none(),
            ephemeral=True,
        )


class OptionName(IntEnum):
    DECAY_AFTER = 1
    INACTIVITY_WARNING_AFTER = 2
    INACTIVITY_DROP_AFTER = 3
    PLAYERS_REQUIRED = 4
    MAX_PLAYERS = 5
    VOTES_REQUIRED = 6
    FORMAT_SELECTION_MODE = 7
    ROLE_WHITELIST = 8
    ROLE_BLACKLIST = 9

    def __str__(self) -> str:
        match self.value:
            case self.DECAY_AFTER:
                return "Decay after"
            case self.INACTIVITY_DROP_AFTER:
                return "Inactivity drop after"
            case self.INACTIVITY_WARNING_AFTER:
                return "Inactivity warning after"
            case self.PLAYERS_REQUIRED:
                return "Players required"
            case self.MAX_PLAYERS:
                return "Max players"
            case self.VOTES_REQUIRED:
                return "Votes required"
            case self.FORMAT_SELECTION_MODE:
                return "Format selection mode"
            case self.ROLE_WHITELIST:
                return "Role whitelist"
            case self.ROLE_BLACKLIST:
                return "Role blacklist"
            case _:
                raise ValueError("Invalid value for ConfigOption")


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
    @app_commands.describe(format="The method of format selection")
    @app_commands.describe(votes_required="The amount of votes needed to end the vote early")
    @app_commands.rename(format="format_selection_mode")
    @app_commands.choices(format=[
        Choice(name="Vote", value=FormatSelectionMode.VOTE.value),
        Choice(name="Random", value=FormatSelectionMode.RANDOM.value),
    ])
    async def set_config(
        self,
        interaction: discord.Interaction,
        decay_after: int | None,
        inactivity_warning_after: int | None,
        inactivity_drop_after: int | None,
        players_required: int | None,
        max_players: int | None,
        format: app_commands.Choice[int] | None,
        votes_required: int | None,
    ) -> None:
        """
        The /config set command.

        Updates channel configuration.
        """

        # Parse format selection mode
        format_selection_mode = (
            FormatSelectionMode(format.value)
            if format is not None
            else None
        )

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
        options = UpdateRoomOptions.from_dict({
            k: v for k, v in {
                "decay_after": decay_after,
                "inactivity_warning_after": inactivity_warning_after,
                "inactivity_drop_after": inactivity_drop_after,
                "max_players": max_players,
                "players_required": players_required,
                "votes_required": votes_required,
                "format_selection_mode": format_selection_mode,
            }.items() if v is not None
        })

        room = await self.db.update_room(guild.id, room.id, options=options)

        # Build up the config embed
        view = RoomConfigView(interaction.channel, room)
        await interaction.response.send_message(view=view, allowed_mentions=AllowedMentions.none(), ephemeral=True)

    @app_commands.command(name="unset", description="Unsets a config value, resetting it to default")
    @app_commands.choices(option=[
        Choice(name=str(name), value=name.value) for name in list(OptionName)
    ])
    async def unset(self, interaction: discord.Interaction, option: Choice[int]) -> None:
        """
        The /config unset command.

        Unsets a specified value.
        """

        assert interaction.guild
        assert self.command_enable

        name = OptionName(option.value)

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
        options = UpdateRoomOptions()

        if name == OptionName.DECAY_AFTER:
            options.decay_after = None
        if name == OptionName.INACTIVITY_DROP_AFTER:
            options.inactivity_drop_after = None
        if name == OptionName.INACTIVITY_WARNING_AFTER:
            options.inactivity_warning_after = None
        if name == OptionName.PLAYERS_REQUIRED:
            options.players_required = None
        if name == OptionName.VOTES_REQUIRED:
            options.votes_required = None
        if name == OptionName.MAX_PLAYERS:
            options.max_players = None
        if name == OptionName.FORMAT_SELECTION_MODE:
            options.format_selection_mode = None
        if name == OptionName.ROLE_BLACKLIST:
            options.role_blacklist = None
        if name == OptionName.ROLE_WHITELIST:
            options.role_whitelist = None
            
        room = await self.db.update_room(guild.id, room.id, options=options)

        # Build up the config embed
        view = RoomConfigView(interaction.channel, room)
        await interaction.response.send_message(view=view, allowed_mentions=AllowedMentions.none(), ephemeral=True)

    @app_commands.command(name="whitelist", description="Edit the queue whitelist")
    async def whitelist(self, interaction: discord.Interaction) -> None:
        """
        The /config whitelist command.

        Edits the queue whitelist.
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

        await interaction.response.send_modal(RoleWhitelistModal(interaction.channel, room, self.db))

    @app_commands.command(name="blacklist", description="Edit the queue blacklist")
    async def blacklist(self, interaction: discord.Interaction) -> None:
        """
        The /config blacklist command.

        Edits the queue blacklist.
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

        await interaction.response.send_modal(RoleBlacklistModal(interaction.channel, room, self.db))

class FormatConfigModule(
    GroupModule,
    name = "formats",
    description = "Add or remove formats to the room",
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

    async def format_name_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[Choice[int] | Choice[str]]:
        assert interaction.guild

        # Skip calls in non text channels
        if not isinstance(interaction.channel, discord.TextChannel):
            return []

        # Get or create guild
        guild = await self.db.get_guild(interaction.guild.id)
        if guild is None:
            # Unconfigured guild means no formats
            return []

        # Fetch room, and check if it's enabled
        room = await self.db.get_room(guild.id, interaction.channel.id)
        if room is None:
            # Unconfigured room means no formmats
            return []
        assert not isinstance(room.formats, Unset)

        # Get server list
        choices = [Choice(name=format.name, value=format.id) for format in room.formats]
        return [c for c in choices if current.lower() in c.name.lower()]

    @app_commands.command(name="add", description="Adds a new format to the room")
    @app_commands.choices(team_mode=[
        Choice(name=str(name), value=name.value) for name in list(TeamMode)
    ])
    async def add(
        self,
        interaction: discord.Interaction,
        name: str | None,
        team_mode: Choice[int] | None,
    ) -> None:
        """
        The /formats add command.

        Adds a new format to the room.
        """

        assert interaction.guild
        assert self.command_enable

        defaults = FormatDefaults()
        if name is not None:
            defaults.name = name
        if team_mode is not None:
            defaults.team_mode = TeamMode(team_mode.value)

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

        # Open up modal
        modal = FormatModal(interaction.channel, room, None, self.db, defaults=defaults)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="edit", description="Edits a room format")
    @app_commands.autocomplete(format_id=format_name_autocomplete)
    async def edit(self, interaction: discord.Interaction, format_id: int) -> None:
        """
        The /formats edit command.

        Edits a format's details.
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

        # Fetch event format
        format = await self.db.get_event_format(guild.id, room.id, format_id)
        if format is None:
            await interaction.response.send_message(
                f"Format with id `{format_id}` not found.",
                ephemeral=True,
            )
            return

        # Open up modal
        modal = FormatModal(interaction.channel, room, format, self.db)
        await interaction.response.send_modal(modal)


    @app_commands.command(name="remove", description="Removes a format from the room")
    @app_commands.autocomplete(format_id=format_name_autocomplete)
    async def remove(
        self,
        interaction: discord.Interaction,
        format_id: int,
    ) -> None:
        """
        The /formats remove command.

        Removes a new format from the room.
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

        # Delete event format
        try:
            await self.db.delete_event_format(guild.id, room.id, format_id)

            assert not isinstance(room.formats, Unset)
            room.formats = [format for format in room.formats if format.id != format_id]
        except ApiError as err:
            if err.is_not_found():
                await interaction.response.send_message(
                    f"Format with id `{format_id}` not found.",
                    ephemeral=True,
                )
                return
            else:
                raise

        # Build up the config embed
        view = RoomConfigView(interaction.channel, room)
        await interaction.response.send_message(view=view, allowed_mentions=AllowedMentions.none(), ephemeral=True)
