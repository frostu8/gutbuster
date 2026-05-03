import discord
import datetime
from enum import Enum, unique
from dataclasses import dataclass, field
from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from .format import FormatSelectMode, TeamMode, EventFormat
from .guild import Guild, create_guild, get_guild


@dataclass(kw_only=True)
class Room(object):
    """
    A single event room.

    Channels in Discord may have an associated room.
    """

    id: int
    guild: Guild
    channel: discord.TextChannel | discord.Object
    enabled: bool = field(default=True)
    players_required: int = field(default=8)
    format_selection_mode: FormatSelectMode = field(default=FormatSelectMode.VOTE)
    votes_required: int = field(default=4)
    # TODO add to config
    inactivity_warning_after: int = field(default=1500)
    inactivity_drop_after: int = field(default=2100)
    formats: Optional[List[EventFormat]] = field(default=None)
    inserted_at: datetime.datetime
    updated_at: datetime.datetime

    async def preload_formats(self, conn: AsyncConnection) -> List[EventFormat]:
        """
        Loads the list of formats the room supports.
        """

        if self.formats is not None:
            return self.formats

        res = await conn.execute(
            text("""
            SELECT id, name, team_mode
            FROM event_format
            WHERE room_id = :room_id
            """),
            {"room_id": self.id},
        )

        self.formats = []
        for row in res:
            format = EventFormat(row.id, name=row.name, team_mode=TeamMode(row.team_mode))
            self.formats.append(format)

        return self.formats

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

        if self.formats is None:
            format_list = await self.preload_formats(conn)
        else:
            format_list = self.formats

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
        format_list.append(format)
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

    # Get or create the guild
    guild = await get_guild(channel.guild, conn)
    if guild is None:
        guild = await create_guild(channel.guild, conn)

    # Initialize with default settings
    now = datetime.datetime.now()

    res = await conn.execute(
        text("""
        INSERT INTO room (guild_id, discord_channel_id, enabled, inserted_at, updated_at)
        VALUES (:guild_id, :channel_id, :enabled, :now, :now)
        RETURNING id
        """),
        {"guild_id": guild.id, "channel_id": channel.id, "enabled": enabled, "now": now.isoformat()},
    )

    row = res.first()
    if row is None:
        raise ValueError("failed to get id of new room")

    room = Room(
        id=row.id,
        guild=guild,
        channel=channel,
        enabled=enabled,
        inserted_at=now,
        updated_at=now,
    )

    # We can safely say there's no formats on newly created rooms
    #await room.preload_formats(conn)
    return room


async def get_room(
    channel: discord.TextChannel, conn: AsyncConnection
) -> Optional[Room]:
    """
    Gets a room of a channel.

    If no room exists, this returns `None`.
    """

    # Get the guild
    guild = await get_guild(channel.guild, conn)
    if guild is None:
        # If the guild hasn't been made, the room also does not exist
        return None

    res = await conn.execute(
        text("""
        SELECT id, enabled, players_required, format_selection_mode, votes_required, inserted_at, updated_at
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
        guild=guild,
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
