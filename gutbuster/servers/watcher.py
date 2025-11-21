from .server import Server
from .packet import ServerInfo, PlayerInfo
from typing import List, Dict, Optional, Generator, Tuple
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection
import discord
import asyncio


class WatchedServer(Server):
    id: int
    discord_guild_id: int
    inserted_at: datetime
    updated_at: datetime

    last_updated: Optional[datetime]
    update_event: asyncio.Event

    def __init__(
        self,
        remote: str,
        *,
        id: int,
        discord_guild_id: int,
        label: Optional[str] = None,
        inserted_at: datetime,
        updated_at: datetime,
    ):
        super().__init__(remote, label=label)

        self.id = id
        self.discord_guild_id = discord_guild_id
        self.inserted_at = inserted_at
        self.updated_at = updated_at

        self.last_updated = None
        self.update_event = asyncio.Event()

    async def update_label(self, label: str, conn: AsyncConnection) -> None:
        """
        Updates the server label.
        """

        self.label = label

        now = datetime.now()
        await conn.execute(
            text("""
            UPDATE server
            SET label = :label, updated_at = :now
            WHERE id = :id
            """),
            {"id": self.id, "label": label, "now": now.isoformat()}
        )

    async def knock(self) -> Tuple[ServerInfo, List[PlayerInfo]]:
        res = await super().knock()
        self.last_updated = datetime.now(timezone.utc)

        # Notify waiting tasks
        self.update_event.set()
        self.update_event.clear()

        return res


class ServerWatcher:
    """
    A Ring Racers server watcher.
    """

    servers: Dict[int, WatchedServer]
    servers_by_guild: Dict[int, List[WatchedServer]]

    db: AsyncEngine

    def __init__(self, db: AsyncEngine):
        self.db = db

        self.servers = {}
        self.servers_by_guild = {}

    def _append(self, server: WatchedServer) -> None:
        self.servers[server.id] = server

        if server.discord_guild_id in self.servers_by_guild.keys():
            self.servers_by_guild[server.discord_guild_id].append(server)
        else:
            self.servers_by_guild[server.discord_guild_id] = [server]

    async def knock(self) -> None:
        """
        Updates the server info for all tracked servers.
        """

        for server in self.servers.values():
            await server.knock()

    async def add(
        self,
        guild: discord.Guild | discord.Object,
        remote: str,
        *,
        label: Optional[str] = None,
    ) -> WatchedServer:
        """
        Adds a new server to the watcher.
        """

        now = datetime.now()
        row = None

        async with self.db.connect() as conn:
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

            await conn.commit()

        server = WatchedServer(
            id=row.id,
            discord_guild_id=guild.id,
            remote=remote,
            label=label,
            inserted_at=now,
            updated_at=now,
        )
        self._append(server)
        return server

    def iter(
        self, guild: Optional[discord.Guild | discord.Object] = None
    ) -> Generator[WatchedServer, None, None]:
        """
        Iterates over all servers attached to a guild.
        """

        if guild is None:
            for server in self.servers.values():
                yield server
        else:
            if guild.id in self.servers_by_guild:
                servers = self.servers_by_guild[guild.id]
                for server in servers:
                    yield server

    async def remove(self, server: WatchedServer) -> None:
        """
        Removes a server from the watcher.
        """

        async with self.db.connect() as conn:
            _res = await conn.execute(
                text("""
                DELETE FROM server
                WHERE id = :id
                """),
                {"id": server.id},
            )
            await conn.commit()

        self.servers.pop(server.id)

        if server.discord_guild_id in self.servers_by_guild:
            servers = self.servers_by_guild[server.discord_guild_id]
            servers.remove(server)

    async def load(self) -> None:
        """
        Loads all servers from the internal server database.
        """

        async with self.db.connect() as conn:
            res = await conn.execute(
                text("""
                SELECT id, discord_guild_id, remote, label, inserted_at, updated_at
                FROM server
                """)
            )

        for row in res:
            server = WatchedServer(
                id=row.id,
                discord_guild_id=row.discord_guild_id,
                remote=row.remote,
                label=row.label,
                inserted_at=datetime.fromisoformat(row.inserted_at),
                updated_at=datetime.fromisoformat(row.updated_at),
            )
            self._append(server)
