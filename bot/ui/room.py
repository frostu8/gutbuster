import discord
from discord import ui, SeparatorSpacing

from mogidb import Unset
from mogidb.model import FormatSelectionMode, Room


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

        self.clear_items()

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
                content += f"\n`{server.remote}` - {server.label}"

            self.add_item(ui.TextDisplay(content))


class RoomConfigView(ui.LayoutView):
    container: RoomConfigContainer
    
    def __init__(self, channel: discord.TextChannel, room: Room, *, timeout: float | None = 0):
        super().__init__(timeout=timeout)
        self.container = RoomConfigContainer(channel, room)
        self.add_item(self.container)

        
