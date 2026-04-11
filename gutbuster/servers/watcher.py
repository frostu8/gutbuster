from .server import Server
from .packet import ServerInfo, PlayerInfo
from typing import List, Dict, Optional, Generator, Tuple
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection
from gutbuster.model import Server as SavedServer, create_server, get_all_servers
import discord
import asyncio


class WatchedServer(Server):
    inner: SavedServer

    last_updated: Optional[datetime]
    update_event: asyncio.Event

    def __init__(self, inner: SavedServer):
        super().__init__(inner.remote, label=inner.label)

        self.inner = inner

        self.last_updated = None
        self.update_event = asyncio.Event()

    @property
    def id(self):
        return self.inner.id

    @property
    def discord_guild_id(self):
        return self.inner.discord_guild_id

    async def set_label(self, label: str, conn: AsyncConnection) -> None:
        await self.inner.set_label(label, conn)

    async def knock(self, *, timeout: int | float = 5) -> Tuple[ServerInfo, List[PlayerInfo]]:
        res = await super().knock(timeout=timeout)
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

        async with self.db.connect() as conn:
            db_server = await create_server(guild, remote, conn, label=label)
            await conn.commit()

        server = WatchedServer(inner=db_server)
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

        try:
            server = self.servers.pop(server.id)
        except KeyError:
            raise ValueError(f"Server {server.remote} not found.")

        async with self.db.connect() as conn:
            await server.inner.delete(conn)
            await conn.commit()

        # Remove from guild list
        if server.discord_guild_id in self.servers_by_guild:
            servers = self.servers_by_guild[server.discord_guild_id]
            servers.remove(server)

    async def load(self) -> None:
        """
        Loads all servers from the internal server database.
        """

        async with self.db.connect() as conn:
            servers = await get_all_servers(conn)

        for db_server in servers:
            server = WatchedServer(db_server)
            self._append(server)
