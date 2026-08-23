import datetime
from dataclasses import dataclass, field
from datetime import UTC
from typing import List, Optional

import discord
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import text

from mogidb.model import Guild as ApiGuild

from .format import FormatSelectMode


@dataclass(kw_only=True)
class PersistentStatus:
    """
    A board for displaying server information.
    """

    id: int
    guild: ApiGuild
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


async def list_boards(guild: ApiGuild, conn: AsyncConnection) -> list[PersistentStatus]:
    """
    Loads the list of boards in a guild.
    """

    res = await conn.execute(
        text("""
        SELECT id, guild_id, discord_channel_id, discord_message_id, inserted_at, updated_at
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

async def create_board(
    guild: ApiGuild,
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
        RETURNING id
        """),
        {"guild_id": guild.id, "channel_id": channel.id, "now": now.isoformat()}
    )

    row = res.first()
    if row is None:
        raise ValueError("failed to get id of new guild")

    return PersistentStatus(
        id=row.id,
        guild=guild,
        channel=channel,
        message=None,
        inserted_at=now,
        updated_at=now,
    )


@dataclass(kw_only=True)
class Guild(object):
    """
    A guild.
    """

    id: int
    guild: discord.Guild | discord.Object

    # List of boards
    persistent_statuses: Optional[List[PersistentStatus]] = field(default=None)

    # Default config options for channels
    players_required: int = field(default=8)
    format_selection_mode: FormatSelectMode = field(default=FormatSelectMode.VOTE)
    votes_required: int = field(default=4)
    # TODO add to config
    inactivity_warning_after: int = field(default=1500)
    inactivity_drop_after: int = field(default=2100)
    inserted_at: datetime.datetime
    updated_at: datetime.datetime


async def create_guild(
    guild: discord.Guild,
    conn: AsyncConnection,
) -> Guild:
    """
    Registers a new guild, initializing it with default settings.
    """

    # Initialize with default settings
    now = datetime.datetime.now()

    res = await conn.execute(
        text("""
        INSERT INTO guild (discord_guild_id, inserted_at, updated_at)
        VALUES (:guild_id, :now, :now)
        RETURNING id
        """),
        {"guild_id": guild.id, "now": now.isoformat()}
    )

    row = res.first()
    if row is None:
        raise ValueError("failed to get id of new guild")

    return Guild(
        id=row.id,
        guild=guild,
        inserted_at=now,
        updated_at=now
    )


async def get_guild(
    guild: discord.Guild | discord.Object,
    conn: AsyncConnection,
) -> Optional[Guild]:
    """
    Gets a guild.
    """

    res = await conn.execute(
        text("""
        SELECT *
        FROM guild
        WHERE discord_guild_id = :id
        """),
        {"id": guild.id}
    )

    row = res.first()
    if row is None:
        return None

    return Guild(
        id=row.id,
        guild=guild,
        players_required=row.players_required,
        format_selection_mode=FormatSelectMode(row.format_selection_mode),
        votes_required=row.votes_required,
        inserted_at=datetime.datetime.fromisoformat(row.inserted_at),
        updated_at=datetime.datetime.fromisoformat(row.updated_at),
    )

async def list_all_boards(conn: AsyncConnection) -> list[PersistentStatus]:
    res = await conn.execute(
        text("""
        SELECT
            pin.*,
            g.discord_guild_id, g.players_required, g.format_selection_mode,
            g.votes_required,
            g.inserted_at AS guild_inserted_at,
            g.updated_at AS guild_updated_at
        FROM persistent_status pin, guild g
        WHERE pin.guild_id = g.id
        """),
    )

    pinned = []
    for row in res:
        guild = Guild(
            id=row.guild_id,
            guild=discord.Object(row.discord_guild_id),
            players_required=row.players_required,
            format_selection_mode=row.format_selection_mode,
            votes_required=row.votes_required,
            inserted_at=datetime.datetime.fromisoformat(row.guild_inserted_at),
            updated_at=datetime.datetime.fromisoformat(row.guild_updated_at),
        )

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
