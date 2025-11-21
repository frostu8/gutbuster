from .packet import ServerInfo, Packet, ServerInfoPacket, AskPacket, strip_colors, PlayerInfo, PacketError, PlayerInfoPacket, MAX_PLAYERS
from typing import Optional, List, Tuple
import asyncudp
import asyncio
import ipaddress
import logging
import socket
from datetime import datetime, timedelta


logger = logging.getLogger(__name__)


class ConnectError(Exception):
    """
    An error for connection failures.
    """

    def __init__(self, *args):
        super().__init__(*args)


class Server:
    """
    A Ring Racers server.
    """

    remote: str

    ip: ipaddress.IPv4Address | ipaddress.IPv6Address
    port: int

    tries: int

    label: Optional[str]

    info: Optional[ServerInfo]
    players: List[PlayerInfo]

    pings: List[int]

    _server_name: Optional[str]

    def __init__(self, remote: str, *, label: Optional[str] = None, tries: int = 5):
        self.remote = remote
        self.label = label
        self.tries = tries

        ip, separator, port = remote.rpartition(":")
        self.ip = ipaddress.ip_address(socket.gethostbyname(ip))

        if separator:
            self.port = int(port)
        else:
            self.port = 5029

        self.info = None
        self.players = []

        self.pings = []
        self._server_name = None

    @property
    def map_title(self) -> Optional[str]:
        if self.info is None:
            return None

        map_title = self.info.map_title
        if self.info.is_zone:
            map_title += " Zone"
        if self.info.actnum > 0:
            map_title += f" {self.info.actnum}"

        return map_title

    @property
    def server_name(self) -> Optional[str]:
        """
        The plaintext name of the server.
        """

        if self.info is None:
            return None

        return strip_colors(self.info.server_name)

    @property
    def ping(self) -> float:
        return sum(self.pings) / len(self.pings)

    async def knock(self, *, timeout: int | float = 5) -> Tuple[ServerInfo, List[PlayerInfo]]:
        """
        Asks for a ``ServerInfo`` frm the remote.
        """

        remote_addr = (str(self.ip), self.port)

        # Create a socket to use for the lifetime of the knock
        async with await asyncudp.create_socket(remote_addr=remote_addr) as socket:
            # Ask multiple times
            tries = 0

            while tries < self.tries:
                try:
                    info, players = await self._get_info(socket, timeout)

                    self.info = info
                    self.players = players

                    return info, players
                except TimeoutError:
                    tries += 1

        raise ConnectError(f"Failed to get server info after {tries} tries")

    async def _ask(self, socket: asyncudp.Socket, timeout: int | float = 5) -> bytes:
        # Creates an ask packet.
        packet = AskPacket().pack()

        start_time = datetime.now()
        socket.sendto(packet)

        logger.debug("Sending ask packet")

        buf, _ = await asyncio.wait_for(socket.recvfrom(), timeout)
        end_time = datetime.now()

        if len(self.pings) > 5: # TODO magic
            self.pings.pop(0)
        self.pings.append((end_time - start_time).total_seconds() * 1000)

        return buf

    async def _get_info(self, socket: asyncudp.Socket, timeout: int | float = 5) -> Tuple[ServerInfo, List[PlayerInfo]]:
        timeout_at = datetime.now() + timedelta(seconds=timeout)

        # Collect data
        info = None
        players = []

        first = True
        while info is None or len(players) < info.number_of_players:
            start_time = datetime.now()
            wait = max((timeout_at - start_time).total_seconds(), 0.0)

            # Get data from server
            if first:
                # We need to ask for the data from the server to get some data
                buf = await self._ask(socket, wait)
                first = False
            else:
                buf, _ = await asyncio.wait_for(socket.recvfrom(), wait)

            try:
                res = Packet.unpack(buf)

                if isinstance(res, ServerInfoPacket):
                    info = res.info
                if isinstance(res, PlayerInfoPacket):
                    players.extend(p for p in res.players if not p.is_empty)
            except PacketError as err:
                logger.warning(f"Got error {err} knocking for server {self.remote}")

        return info, players
