from sqlalchemy.sql import text
from sqlalchemy.ext.asyncio import AsyncConnection
import discord
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass, field
from .guild import Guild
from .format import FormatSelectMode, EventFormat

@dataclass(kw_only=True)
class Server:
    id: int
    guild: Guild
    remote: str
    label: Optional[str] = field(default=None)
    description: Optional[str] = field(default=None)
    inserted_at: datetime
    updated_at: datetime

    async def set_label(self, label: str, conn: AsyncConnection) -> None:
        """
        Updates the server label.
        """

        now = datetime.now()
        await conn.execute(
            text("""
            UPDATE server
            SET label = :label, updated_at = :now
            WHERE id = :id
            """),
            {"id": self.id, "label": label, "now": now.isoformat()}
        )

        self.label = label

    async def delete(self, conn: AsyncConnection) -> None:
        """
        Deletes this server from the database.
        """

        await conn.execute(
            text("""
            DELETE FROM server
            WHERE id = :id
            """),
            {"id": self.id},
        )


async def create_server(
    guild: Guild,
    remote: str,
    conn: AsyncConnection,
    *,
    label: Optional[str] = None,
    description: Optional[str] = None,
) -> Server:
    """
    Creates a new server and registers it to the guild.
    """

    now = datetime.now()

    res = await conn.execute(
        text("""
        INSERT INTO server (guild_id, remote, label, inserted_at, updated_at)
        VALUES (:guild_id, :remote, :label, :now, :now)
        RETURNING id
        """),
        {
            "guild_id": guild.id,
            "remote": remote,
            "label": label,
            "now": now.isoformat(),
        },
    )

    row = res.first()
    if row is None:
        raise ValueError("Failed to get generated id of row")

    return Server(
        id=row.id,
        guild=guild,
        remote=remote,
        label=label,
        description=description,
        inserted_at=now,
        updated_at=now
    )


async def get_all_servers(conn: AsyncConnection, *, guild: Optional[discord.Object] = None) -> List[Server]:
    """
    Returns all servers.

    The `guild` parameter may be used to restrict the servers the guild belongs
    to.
    """

    res = await conn.execute(
        text("""
        SELECT
            s.*,
            g.discord_guild_id,
            g.players_required, g.format_selection_mode, g.votes_required,
            g.inserted_at AS guild_inserted_at,
            g.updated_at AS guild_updated_at
        FROM server s, guild g
        WHERE
            (:guild_id IS NULL OR discord_guild_id = :guild_id)
            AND s.guild_id = g.id
        """),
        {"guild_id": guild and guild.id}
    )

    servers = []
    for row in res:
        model_guild = Guild(
            id=row.guild_id,
            guild=discord.Object(row.discord_guild_id),
            players_required=row.players_required,
            format_selection_mode=FormatSelectMode(row.format_selection_mode),
            votes_required=row.votes_required,
            inserted_at=datetime.fromisoformat(row.guild_inserted_at),
            updated_at=datetime.fromisoformat(row.guild_updated_at),
        )

        servers.append(Server(
            id=row.id,
            guild=model_guild,
            remote=row.remote,
            label=row.label,
            description=row.description,
            inserted_at=datetime.fromisoformat(row.inserted_at),
            updated_at=datetime.fromisoformat(row.updated_at),
        ))

    return servers

async def find_server(format: EventFormat, conn: AsyncConnection) -> Optional[Server]:
    """
    Finds an available server to host the event.

    This automatically updates the event's remote with the server, and
    returns the found server.
    """

    res = await conn.execute(
        text("""
        SELECT
            s.*,
            g.discord_guild_id,
            g.players_required, g.format_selection_mode, g.votes_required,
            g.inserted_at AS guild_inserted_at,
            g.updated_at AS guild_updated_at
        FROM event_format ef, event_format_server relation, server s, guild g
        WHERE
            ef.id = relation.event_format_id
            AND s.guild_id = g.id
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
        {"format_id": format.id}
    )

    row = res.first()
    if row is None:
        return None

    guild = Guild(
        id=row.guild_id,
        guild=discord.Object(row.discord_guild_id),
        players_required=row.players_required,
        format_selection_mode=FormatSelectMode(row.format_selection_mode),
        votes_required=row.votes_required,
        inserted_at=datetime.fromisoformat(row.guild_inserted_at),
        updated_at=datetime.fromisoformat(row.guild_updated_at),
    )
    
    return Server(
        id=row.id,
        guild=guild,
        remote=row.remote,
        label=row.label,
        inserted_at=row.inserted_at,
        updated_at=row.updated_at,
    )

