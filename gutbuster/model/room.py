import discord
import datetime
from enum import Enum, unique
from dataclasses import dataclass, field
from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from .server import Server


@unique
class FormatSelectMode(Enum):
    """
    How to select formats in an event.
    """
    VOTE = 0
    RANDOM = 1


@unique
class TeamMode(Enum):
    """
    How to assign teams to players after the mogi has gathered.
    """
    FREE_FOR_ALL = 0
    TWO_TEAMS = 2
    THREE_TEAMS = 3
    FOUR_TEAMS = 4

    def has_equal_teams(self, player_count: int) -> bool:
        """
        Given a player count `player_count`, will the teams have equal players?
        Returs `true` if they will have equal players.
        """

        match self:
            case TeamMode.FREE_FOR_ALL:
                # Free for all will always have equal teams
                return True
            case (
                TeamMode.TWO_TEAMS
                | TeamMode.THREE_TEAMS
                | TeamMode.FOUR_TEAMS
            ):
                team_count = self.value
                return player_count % team_count == 0
            case _:
                return False


@dataclass
class EventFormat(object):
    """
    An event format
    """

    id: int
    name: str = field(kw_only=True)
    team_mode: TeamMode = field(kw_only=True)

    async def find_server(self, conn: AsyncConnection) -> Optional[Server]:
        """
        Finds an available server to host the event.

        This automatically updates the event's remote with the server, and
        returns the found server.
        """

        res = await conn.execute(
            text("""
            SELECT s.*
            FROM event_format ef, event_format_server relation, server s
            WHERE
                ef.id = relation.event_format_id
                AND s.id = relation.server_id
                AND ef.id = :format_id
                AND s.remote NOT IN (
                    SELECT s.remote
                    FROM server s, event e
                    WHERE
                    e.remote = s.remote
                    AND (e.status = 0 OR e.status = 1)
                )
            ORDER BY s.inserted_at ASC
            LIMIT 1
            """),
            {"format_id": self.id}
        )

        row = res.first()
        if row is None:
            return None
        
        return Server(
            id=row.id,
            discord_guild_id=row.discord_guild_id,
            remote=row.remote,
            label=row.label,
            inserted_at=row.inserted_at,
            updated_at=row.updated_at,
        )


@dataclass(kw_only=True)
class Room(object):
    """
    A single event room.

    Channels in Discord may have an associated room.
    """

    id: int
    discord_guild_id: int
    channel: discord.TextChannel | discord.Object
    enabled: bool = field(default=True)
    players_required: int = field(default=8)
    format_selection_mode: FormatSelectMode = field(default=FormatSelectMode.VOTE)
    votes_required: int = field(default=4)
    inactivity_warning_after: int = field(default=900)
    inactivity_drop_after: int = field(default=1500)
    formats: List[EventFormat] = field(default_factory=lambda: [])
    inserted_at: datetime.datetime
    updated_at: datetime.datetime

    async def preload_formats(self, conn: AsyncConnection):
        """
        Loads the list of formats the room supports.
        """

        res = await conn.execute(
            text("""
            SELECT id, name, team_mode
            FROM event_format
            WHERE room_id = :room_id
            """),
            {"room_id": self.id},
        )

        self.formats.clear()
        for row in res:
            format = EventFormat(row.id, name=row.name, team_mode=TeamMode(row.team_mode))
            self.formats.append(format)

    async def add_format(
        self,
        name: str,
        conn: AsyncConnection,
        *,
        team_mode: TeamMode = TeamMode.FREE_FOR_ALL
    ) -> EventFormat:
        """
        Adds a format to the room.
        """

        res = await conn.execute(
            text("""
            INSERT INTO event_format (room_id, name, team_mode)
            VALUES (:room_id, :name, :team_mode)
            RETURNING id
            """),
            {"room_id": self.id, "name": name, "team_mode": team_mode.value},
        )

        row = res.first()
        if row is None:
            raise ValueError("failed to get id of new row")

        format = EventFormat(row.id, name=name, team_mode=team_mode)
        self.formats.append(format)
        return format

    async def _set_enabled(self, enabled: bool, conn: AsyncConnection):
        """
        Sets the enabled status of a room.
        """

        now = datetime.datetime.now()
        await conn.execute(
            text("""
            UPDATE room
            SET enabled = :enabled, updated_at = :now
            WHERE id = :id
            """),
            {"id": self.id, "enabled": self.enabled, "now": now.isoformat()},
        )

        self.enabled = enabled

    async def enable(self, conn: AsyncConnection):
        """
        Enables a room.
        """
        await self._set_enabled(True, conn)

    async def disable(self, conn: AsyncConnection):
        """
        Disables a room.

        This preserves the room's settings in the bot.
        """
        await self._set_enabled(False, conn)


async def create_room(
    channel: discord.TextChannel, conn: AsyncConnection, *, enabled: bool = True
) -> Room:
    """
    Creates a new room, initializing it with default settings.
    """

    # Initialize with default settings
    now = datetime.datetime.now()

    res = await conn.execute(
        text("""
        INSERT INTO room (discord_guild_id, discord_channel_id, enabled, inserted_at, updated_at)
        VALUES (:guild_id, :channel_id, :enabled, :now, :now)
        RETURNING id
        """),
        {"guild_id": channel.guild.id, "channel_id": channel.id, "enabled": enabled, "now": now.isoformat()},
    )

    row = res.first()
    if row is None:
        raise ValueError("failed to get id of new room")

    room = Room(
        id=row.id,
        discord_guild_id=channel.guild.id,
        channel=channel,
        enabled=enabled,
        inserted_at=now,
        updated_at=now,
    )

    # We can safely say there's no formats on newly created rooms
    #await room.preload_formats(conn)
    return room


async def get_room(
    channel: discord.TextChannel | discord.Object, conn: AsyncConnection
) -> Optional[Room]:
    """
    Gets a room of a channel.

    If no room exists, this returns `None`.
    """

    res = await conn.execute(
        text("""
        SELECT id, discord_guild_id, enabled, players_required, format_selection_mode, votes_required, inserted_at, updated_at
        FROM room
        WHERE discord_channel_id = :id
        """),
        {"id": channel.id},
    )

    row = res.first()
    if row is None:
        return None

    room = Room(
        id=row.id,
        discord_guild_id=row.discord_guild_id,
        channel=channel,
        enabled=row.enabled,
        players_required=row.players_required,
        format_selection_mode=FormatSelectMode(row.format_selection_mode),
        votes_required=row.votes_required,
        inserted_at=datetime.datetime.fromisoformat(row.inserted_at),
        updated_at=datetime.datetime.fromisoformat(row.updated_at),
    )

    await room.preload_formats(conn)
    return room
