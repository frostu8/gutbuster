from sqlalchemy.sql import text
from sqlalchemy.ext.asyncio import AsyncConnection
import discord
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass, field


@dataclass(kw_only=True)
class Server:
    id: int
    discord_guild_id: int
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
    guild: discord.Guild | discord.Object,
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
        INSERT INTO server (discord_guild_id, remote, label, inserted_at, updated_at)
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
        discord_guild_id=guild.id,
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
        SELECT s.*
        FROM server s
        WHERE :guild_id IS NULL OR discord_guild_id = :guild_id
        """),
        {"guild_id": guild and guild.id}
    )

    servers = []
    for row in res:
        servers.append(Server(
            id=row.id,
            discord_guild_id=row.discord_guild_id,
            remote=row.remote,
            label=row.label,
            description=row.description,
            inserted_at=datetime.fromisoformat(row.inserted_at),
            updated_at=datetime.fromisoformat(row.updated_at),
        ))

    return servers
