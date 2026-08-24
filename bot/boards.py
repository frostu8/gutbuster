import datetime
from dataclasses import dataclass
from datetime import UTC

import discord
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import text

import mogidb
from mogidb.model import Guild


@dataclass(kw_only=True)
class PersistentStatus:
    """
    A board for displaying server information.
    """

    id: int
    guild: Guild
    channel: discord.TextChannel | discord.Object
    message: discord.Message | discord.Object | None
    inserted_at: datetime.datetime
    updated_at: datetime.datetime

    async def set_message(self, message: discord.Message, conn: AsyncConnection):
        """
        Sets the message associated with the persistent status.

        On restarts, the bot will update this.
        """

        now = datetime.datetime.now(UTC)
        await conn.execute(
            text("""
            UPDATE persistent_boards
            SET discord_message_id = :message_id, updated_at = :now
            WHERE id = :id
            """),
            {"id": self.id, "message_id": message.id, "now": now.isoformat()},
        )

        self.message = message

    async def delete(self, conn: AsyncConnection) -> None:
        """
        Deletes the status from the database.
        """

        await conn.execute(
            text("""
            DELETE FROM persistent_boards
            WHERE id = :id
            """),
            {"id": self.id},
        )


async def list_boards(guild: Guild, conn: AsyncConnection) -> list[PersistentStatus]:
    """
    Loads the list of boards in a guild.
    """

    res = await conn.execute(
        text("""
        SELECT *
        FROM persistent_boards
        WHERE guild_id = :guild_id
        """),
        {"guild_id": guild.id},
    )

    persistent_statuses = []
    for row in res:
        board = PersistentStatus(
            id=row.id,
            guild=guild,
            channel=discord.Object(row.discord_channel_id),
            message=row.discord_message_id and discord.Object(row.discord_message_id),
            inserted_at=datetime.datetime.fromisoformat(row.inserted_at),
            updated_at=datetime.datetime.fromisoformat(row.updated_at),
        )
        persistent_statuses.append(board)

    return persistent_statuses


async def list_all_boards(db: mogidb.Client, conn: AsyncConnection) -> list[PersistentStatus]:
    res = await conn.execute(
        text("""
        SELECT *
        FROM persistent_boards
        """),
    )

    guilds: dict[int, Guild] = {}

    pinned = []
    for row in res:
        # Fetch guild
        if row.guild_id in guilds:
            guild = guilds[row.guild_id]
        else:
            guild = await db.get_guild(row.guild_id)

        if guild is None:
            continue

        guilds[row.guild_id] = guild

        pin = PersistentStatus(
            id=row.id,
            guild=guild,
            channel=discord.Object(row.discord_channel_id),
            message=row.discord_message_id and discord.Object(row.discord_message_id),
            inserted_at=datetime.datetime.fromisoformat(row.inserted_at),
            updated_at=datetime.datetime.fromisoformat(row.updated_at),
        )
        pinned.append(pin)

    return pinned


async def create_board(
    guild: Guild,
    channel: discord.TextChannel,
    conn: AsyncConnection,
) -> PersistentStatus:
    """
    Adds a persistent board to the guild.
    """

    now = datetime.datetime.now(UTC)

    res = await conn.execute(
        text("""
        INSERT INTO persistent_boards (guild_id, discord_channel_id, inserted_at, updated_at)
        VALUES (:guild_id, :channel_id, :now, :now)
        """),
        {"guild_id": guild.id, "channel_id": channel.id, "now": now.isoformat()}
    )

    row = res.first()
    if row is None:
        raise ValueError("failed to get id of new board")

    return PersistentStatus(
        id=row.id,
        guild=guild,
        channel=channel,
        message=None,
        inserted_at=now,
        updated_at=now,
    )
