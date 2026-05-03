from sqlalchemy.sql import text
from sqlalchemy.ext.asyncio import AsyncConnection
import datetime
from typing import List, Optional
import discord
from dataclasses import dataclass, field
from .format import FormatSelectMode, EventFormat


@dataclass(kw_only=True)
class PersistentStatus(object):
    """
    A board for displaying server information.
    """

    id: int
    parent: Guild
    channel: discord.TextChannel | discord.Object
    message: Optional[discord.Message | discord.Object]
    inserted_at: datetime.datetime
    updated_at: datetime.datetime


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

    async def preload_boards(self, conn: AsyncConnection) -> List[PersistentStatus]:
        """
        Loads the list of boards in a guild
        """

        if self.persistent_statuses is not None:
            return self.persistent_statuses

        res = await conn.execute(
            text("""
            SELECT id, guild_id, discord_channel_id, discord_message_id
            FROM persistent_status
            WHERE guild_id = :id
            """),
            {"id": self.id},
        )

        self.persistent_statuses = []
        for row in res:
            board = PersistentStatus(
                id=row.id,
                parent=self,
                channel=discord.Object(row.discord_channel_id),
                message=discord.Object(row.discord_message_id),
                inserted_at=datetime.datetime.fromisoformat(row.inserted_at),
                updated_at=datetime.datetime.fromisoformat(row.updated_at),
            )
            self.persistent_statuses.append(board)

        return self.persistent_statuses

    async def add_board(
        self,
        channel: discord.TextChannel,
        conn: AsyncConnection,
    ) -> PersistentStatus:
        """
        Adds a persistent board to the guild.
        """

        if self.persistent_statuses is None:
            status_list = await self.preload_boards(conn)
        else:
            status_list = self.persistent_statuses

        now = datetime.datetime.now()

        res = await conn.execute(
            text("""
            INSERT INTO persistent_status (guild_id, discord_channel_id, inserted_at, updated_at)
            VALUES (:id, :channel_id, :now, :now)
            RETURNING id
            """),
            {"id": self.id, "channel_id": channel.id, "now": now.isoformat()}
        )

        row = res.first()
        if row is None:
            raise ValueError("failed to get id of new guild")

        status = PersistentStatus(
            id=row.id,
            parent=self,
            channel=channel,
            message=None,
            inserted_at=now,
            updated_at=now,
        )
        status_list.append(status)
        return status


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
