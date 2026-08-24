import dataclasses
import traceback
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Self, override

import discord
from discord import (
    AllowedMentions,
    RadioGroupOption,
    SelectOption,
    SeparatorSpacing,
    ui,
)

import mogidb
from mogidb import Unset
from mogidb.model import (
    EventFormat,
    FormatSelectionMode,
    Room,
    TeamMode,
    UpdateRoomOptions,
)


class Seconds:
    seconds: int

    def __init__(self, seconds: int | None = None):
        # HACK: Set default seconds to make code cleaner below
        if seconds is None:
            seconds = 0

        self.seconds = seconds

    def __str__(self) -> str:
        minutes = self.seconds // 60
        seconds = self.seconds % 60

        if minutes > 0 and seconds > 0:
            return f"{minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m"
        else:
            return f"{seconds}s"


def role_list(roles: Iterable[discord.Role]) -> str:
    roles = list(roles)
    if len(roles) > 0:
        return " ".join([role.mention for role in roles])
    else:
        return "Empty"


class RoomConfigContainer(ui.Container):
    channel: discord.TextChannel
    room: Room

    def __init__(self, channel: discord.TextChannel, room: Room):
        super().__init__()
        self.room = room
        self.channel = channel
        self.update()

    def update(self):
        assert self.room.guild
        assert self.room.formats

        assert self.channel.guild

        self.clear_items()

        # Get role mapping
        role_map = {role.id: role for role in self.channel.guild.roles}

        # Show the guild config
        content = f"## {self.channel.mention} queue config\n"

        guild_settings = self.room.guild.settings
        settings = self.room.settings

        # == DECAY AFTER ==
        content += "\n\n**Decay after** <> "
        if settings.decay_after is None:
            content += f"*{Seconds(guild_settings.decay_after)!s}*"
        else:
            content += f"{Seconds(settings.decay_after)!s}"

        content += (
            "\n(in seconds) How long it takes for a queue to decay."
            "\nA **decayed** queue allows users to end the queue before it gathers."
        )

        # == INACTIVITY WARNING AFTER ==
        content += "\n\n**Inactivity warning after** <> "
        if settings.inactivity_warning_after is None:
            content += f"*{Seconds(guild_settings.inactivity_warning_after)!s}*"
        else:
            content += f"{Seconds(settings.inactivity_warning_after)!s}"

        content += "\n(in seconds) The time it takes before queued players are issued an activity warning."

        # == INACTIVITY DROP AFTER ==
        content += "\n\n**Inactivity drop after** <> "
        if settings.inactivity_drop_after is None:
            content += f"*{Seconds(guild_settings.inactivity_drop_after)!s}*"
        else:
            content += f"{Seconds(settings.inactivity_drop_after)!s}"

        content += "\n(in seconds) The time it takes before queued players are dropped for inactivity."

        # == PLAYERS REQUIRED ==
        content += "\n\n**Players required** <> "
        if settings.players_required is None:
            content += f"*{guild_settings.players_required}*"
        else:
            content += str(settings.players_required)

        content += "\nHow many players are required to start a queue."

        # == MAX PLAYERS ==
        content += "\n\n**Max players** <> "
        if settings.max_players is None:
            content += f"*{guild_settings.max_players}*"
        else:
            content += str(settings.max_players)

        content += "\nThe maximum amount of players in a queue, including subs."

        # == FORMAT SELECTION MODE ==
        content += "\n\n**Format selection mode** <> "
        if settings.format_selection_mode is None:
            content += f"*{guild_settings.format_selection_mode!s}*"
        else:
            content += str(settings.format_selection_mode)

        content += "\nThe method of format selection."

        # == VOTES REQUIRED ==
        content += "\n\n**Votes required** <> "
        if settings.votes_required is None:
            content += f"*{guild_settings.votes_required}*"
        else:
            content += str(settings.votes_required)

        content += "\nHow many votes are needed to end the vote early."

        # additional warning for format selection mode
        if self.room.format_selection_mode != FormatSelectionMode.VOTE:
            content += "\n*Only applicable when format selection is set to Vote*"

        # == ROLE WHITELIST ==
        content += "\n\n**Role whitelist** <> "
        if settings.role_whitelist is None:
            assert guild_settings.role_whitelist is not None
            content += f"*{role_list(role_map[id] for id in guild_settings.role_whitelist)}*"
        else:
            content += role_list(role_map[id] for id in settings.role_whitelist)

        content += (
            "\nBy default, this list is empty and does nothing. When there are "
            "roles here, **only** members with at least one role in this list "
            "are allowed to can in the room."
        )

        # == ROLE BLACKLIST ==
        content += "\n\n**Role blacklist** <> "
        if settings.role_blacklist is None:
            assert guild_settings.role_blacklist is not None
            content += f"*{role_list(role_map[id] for id in guild_settings.role_blacklist)}*"
        else:
            content += role_list(role_map[id] for id in settings.role_blacklist)

        content += (
            "\nBy default, this list is empty. Members with *any* of these roles "
            "are not permitted to can in this room, even if they have a "
            "whitelist role."
        )

        self.add_item(ui.TextDisplay(content))

        if len(self.room.formats) > 0:
            self.add_item(ui.Separator(spacing=SeparatorSpacing.large))

        # For each format, build the config
        for format in self.room.formats:
            assert not isinstance(format.servers, Unset)

            content = f"**Format {format.name}**"

            content += f"\n**Team mode** <> {format.team_mode!s}"

            if len(format.servers) > 0:
                content += "\n**Servers**"

            for server in format.servers:
                status_icon = "🔴"
                if server.info is not None:
                    status_icon = "🟢"
                content += f"\n{status_icon} `{server.remote}` - {server.label}"

            self.add_item(ui.TextDisplay(content))


class RoomConfigView(ui.LayoutView):
    container: RoomConfigContainer
    
    def __init__(self, channel: discord.TextChannel, room: Room, *, timeout: float | None = 0):
        super().__init__(timeout=timeout)
        self.container = RoomConfigContainer(channel, room)
        self.add_item(self.container)


class BaseRoleModal(ui.Modal):
    db: mogidb.Client
    channel: discord.TextChannel
    room: Room

    _description: ui.TextDisplay
    _roles: ui.Label

    def __init__(self, channel: discord.TextChannel, room: Room, db: mogidb.Client, *, timeout: float | None = 180):
        super().__init__(timeout=timeout)

        self.db = db
        self.channel = channel
        self.room = room

        self._description = ui.TextDisplay(self.description)
        self._roles = ui.Label(
            text=self.label(),
            component=ui.RoleSelect(
                placeholder=self.label(),
                min_values=0,
                max_values=10,
            )
        )

        self.add_item(self._description)
        self.add_item(self._roles)

    @property
    def roles(self) -> list[discord.Role]:
        assert isinstance(self._roles.component, ui.RoleSelect)
        return self._roles.component.values

    @property
    def description(self) -> str:
        raise NotImplementedError()

    def label(self) -> str:
        raise NotImplementedError()

    @override
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await interaction.response.send_message("Oops! Something went wrong.", ephemeral=True)

        # Make sure we know what the error actually is
        traceback.print_exception(type(error), error, error.__traceback__)


class RoleWhitelistModal(BaseRoleModal, title="Role whitelist"):
    def __init__(self, channel: discord.TextChannel, room: Room, db: mogidb.Client, *, timeout: float | None = 180):
        super().__init__(channel, room, db, timeout=timeout)
        assert isinstance(self._roles.component, ui.RoleSelect)

        # Get roles initializer
        role_map = {role.id: role for role in self.channel.guild.roles}

        whitelist = self.room.settings.role_whitelist or []
        whitelist = [role_map[id] for id in whitelist]

        self._roles.component.default_values = whitelist

    @override
    async def on_submit(self, interaction: discord.Interaction):
        assert self.room.guild

        # Get role ids
        new_whitelist = [role.id for role in self.roles]

        # Push to server
        self.room = await self.db.update_room(
            self.room.guild.id,
            self.room.id,
            options=UpdateRoomOptions(role_whitelist=new_whitelist),
        )

        view = RoomConfigView(self.channel, self.room)
        await interaction.response.send_message(
            view=view,
            allowed_mentions=AllowedMentions.none(),
            ephemeral=True,
        )

    @property
    @override
    def description(self) -> str:
        return (
            f"*Editing room {self.channel.mention}'s whitelist.*\n"
            "By default, this list is empty and does nothing. When there are "
            "roles here, **only** members with at least one role in this list "
            "are allowed to can in the room.\n\n"
            "When this is set, the bot will tag the roles instead of @ here "
            "when reaching queue milestones or when /ping is sent."
        )

    @override
    def label(self) -> str:
        return "Whitelist"


class RoleBlacklistModal(BaseRoleModal, title="Role blacklist"):
    def __init__(self, channel: discord.TextChannel, room: Room, db: mogidb.Client, *, timeout: float | None = 180):
        super().__init__(channel, room, db, timeout=timeout)
        assert isinstance(self._roles.component, ui.RoleSelect)

        # Get roles initializer
        role_map = {role.id: role for role in self.channel.guild.roles}

        blacklist = self.room.settings.role_blacklist or []
        blacklist = [role_map[id] for id in blacklist]

        self._roles.component.default_values = blacklist

    @override
    async def on_submit(self, interaction: discord.Interaction):
        assert self.room.guild

        # Get role ids
        new_blacklist = [role.id for role in self.roles]

        # Push to server
        self.room = await self.db.update_room(
            self.room.guild.id,
            self.room.id,
            options=UpdateRoomOptions(role_blacklist=new_blacklist),
        )

        view = RoomConfigView(self.channel, self.room)
        await interaction.response.send_message(
            view=view,
            allowed_mentions=AllowedMentions.none(),
            ephemeral=True,
        )

    @property
    @override
    def description(self) -> str:
        return (
            f"*Editing room {self.channel.mention}'s blacklist.*\n"
            "By default, this list is empty. Members with *any* of these roles "
            "are not permitted to can in this room, even if they have a "
            "whitelist role."
        )

    @override
    def label(self) -> str:
        return "Blacklist"


TEAM_MODE_DESCRIPTION: Final = {
    TeamMode.FFA: "Each player plays for their own score.",
    TeamMode.TWO_TEAMS: "Players are sorted into two different teams.",
    TeamMode.THREE_TEAMS: "Players are sorted into three different teams.",
    TeamMode.FOUR_TEAMS: "Players are sorted into four different teams.",
}


@dataclass
class FormatDefaults:
    name: str = ""
    team_mode: TeamMode = TeamMode.FFA
    servers: set[int] = dataclasses.field(default_factory=set)

    @classmethod
    def from_format(cls, format: EventFormat) -> Self:
        assert not isinstance(format.servers, Unset)
        return cls(
            name=format.name,
            team_mode=format.team_mode,
            servers={server.id for server in format.servers}
        )


class FormatModal(ui.Modal, title="Edit format"):
    db: mogidb.Client
    channel: discord.TextChannel
    room: Room
    format_id: int | None

    _description: ui.TextDisplay

    _name: ui.Label
    _team_mode: ui.Label
    _servers: ui.Label

    def __init__(
        self,
        channel: discord.TextChannel,
        room: Room,
        format: EventFormat | None,
        db: mogidb.Client,
        *,
        defaults: FormatDefaults | None = None,
        timeout: float | None = 180,
    ):
        super().__init__(timeout=timeout)

        assert room.guild, "Expected guilds to be loaded"
        assert not isinstance(room.guild.servers, Unset)

        self.db = db
        self.channel = channel
        self.room = room
        self.format_id = None

        guild_servers = room.guild.servers

        # Set defaults for when an event isn't providedd
        defaults = defaults or FormatDefaults()
        if format is not None:
            self.format_id = format.id
            defaults = FormatDefaults.from_format(format)

        self._name = ui.Label(
            text="Name",
            description=(
                "How the format will display in queues and config. "
                "Make it unique!"
            ),
            component=ui.TextInput(min_length=2, default=defaults.name),
        )
        self._team_mode = ui.Label(
            text="Team mode",
            description="Determines how Gutbuster will sort and display teams.",
            component=ui.RadioGroup(options=[
                RadioGroupOption(
                    label=str(mode),
                    value=str(mode.value),
                    description=TEAM_MODE_DESCRIPTION[mode],
                    default=mode == defaults.team_mode
                )
                for mode in list(TeamMode)
            ]),
        )
        self._servers = ui.Label(
            text="Servers",
            description="Servers to use when the format is selected.",
            component=ui.Select(
                placeholder="Select servers",
                min_values=0,
                max_values=len(guild_servers),
                required=False,
                options=[
                    SelectOption(
                        label=server.label,
                        value=str(server.id),
                        description=server.note,
                        emoji="🔴" if server.info is None else "🟢",
                        default=server.id not in defaults.servers
                    )
                    for server in guild_servers
                ],
            ),
        )

        self._description = ui.TextDisplay(self.description)

        self.add_item(self._description)
        self.add_item(self._name)
        self.add_item(self._team_mode)
        self.add_item(self._servers)

    @property
    def description(self) -> str:
        assert isinstance(self._name.component, ui.TextInput)
        name = self._name.component.value

        if len(name) > 0:
            return (
                f"*Editing format* **{name}** "
                f"*for room {self.channel.mention}.*"
            )
        else:
            return f"*Creating new format for room {self.channel.mention}.*"

    @override
    async def on_submit(self, interaction: discord.Interaction):
        assert self.room.guild
        assert not isinstance(self.room.formats, Unset)

        assert isinstance(self._name.component, ui.TextInput)
        assert isinstance(self._team_mode.component, ui.RadioGroup)
        assert isinstance(self._servers.component, ui.Select)

        # Get new format info
        name = self._name.component.value
        team_mode = TeamMode(int(self._team_mode.component.value))

        servers = [int(id) for id in self._servers.component.values]

        # Delete old format if it exists
        if self.format_id is not None:
            await self.db.delete_event_format(self.room.guild.id, self.room.id, self.format_id)

            # Update local copy
            self.room.formats = [format for format in self.room.formats if format.id != self.format_id]
            self.format_id = None

        # Create new format
        new_format = await self.db.create_event_format(
            self.room.guild.id,
            self.room.id,
            name,
            team_mode,
            servers,
        )

        # Update local copy
        self.room.formats.append(new_format)

        view = RoomConfigView(self.channel, self.room)
        await interaction.response.send_message(
            view=view,
            allowed_mentions=AllowedMentions.none(),
            ephemeral=True,
        )

    @override
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await interaction.response.send_message("Oops! Something went wrong.", ephemeral=True)

        # Make sure we know what the error actually is
        traceback.print_exception(type(error), error, error.__traceback__)

