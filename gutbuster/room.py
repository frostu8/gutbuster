import discord
import datetime
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class Room(object):
    """
    A single event room.

    Channels in Discord may have an associated room.
    """

    id: int
    channel: discord.TextChannel
    enabled: bool
    inserted_at: datetime.datetime
    updated_at: datetime.datetime

    def __init__(
        self,
        *,
        id: int,
        channel: discord.TextChannel,
        enabled: bool = True,
        inserted_at: datetime.datetime,
        updated_at: datetime.datetime,
    ):
        self.id = id
        self.channel = channel
        self.enabled = enabled
        self.inserted_at = inserted_at
        self.updated_at = updated_at

    async def _set_enabled(self, enabled: bool, conn: AsyncConnection):
        """
        Sets the enabled status of a room.
        """

        await conn.execute(
            text("""
            UPDATE room
            SET enabled = :enabled
            WHERE id = :id
            """),
            {"id": self.id, "enabled": self.enabled},
        )

        self.enabled = enabled

    async def enable(self, conn: AsyncConnection):
        """
        Enables a room.
        """
        self._set_enabled(True, conn)

    async def disable(self, conn: AsyncConnection):
        """
        Disables a room.

        This preserves the room's settings in the bot.
        """
        self._set_enabled(False, conn)


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
        INSERT INTO room (discord_channel_id, enabled, inserted_at, updated_at)
        VALUES (:id, :enabled, :now, :now)
        RETURNING id
        """),
        {"id": channel.id, "enabled": enabled, "now": now.isoformat()},
    )

    row = res.first()
    if row is None:
        raise ValueError("failed to get id of new room")

    return Room(
        id=row.id, channel=channel, enabled=enabled, inserted_at=now, updated_at=now
    )


async def get_room(
    channel: discord.TextChannel, conn: AsyncConnection
) -> Optional[Room]:
    """
    Gets a room of a channel.

    If no room exists, this returns `None`.
    """

    res = await conn.execute(
        text("""
        SELECT id, enabled, inserted_at, updated_at
        FROM room
        WHERE discord_channel_id = :id
        """),
        {"id": channel.id},
    )

    row = res.first()
    if row is None:
        return None

    return Room(
        id=row.id,
        channel=channel,
        enabled=row.enabled,
        inserted_at=datetime.datetime.fromisoformat(row.inserted_at),
        updated_at=datetime.datetime.fromisoformat(row.updated_at),
    )
