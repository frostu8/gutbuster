from .packet import ServerInfo, Packet, ServerInfoPacket, AskPacket, strip_colors, PlayerInfo, PacketError, PlayerInfoPacket, MAX_PLAYERS
from typing import Optional, List, Tuple
import asyncudp
import asyncio
import ipaddress
import logging
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

    remote: ipaddress.IPv4Address | ipaddress.IPv6Address
    remote_port: int
    tries: int

    label: Optional[str]

    info: Optional[ServerInfo]
    players: List[PlayerInfo]

    pings: List[int]

    _server_name: Optional[str]

    def __init__(self, remote: str, *, label: Optional[str] = None, tries: int = 5):
        ip, separator, port = remote.rpartition(':')
        assert separator

        self.remote = ipaddress.ip_address(ip)
        self.remote_port = int(port)
        self.tries = tries

        self.label = label

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

    async def knock(self) -> Tuple[ServerInfo, List[PlayerInfo]]:
        """
        Asks for a ``ServerInfo`` frm the remote.
        """

        remote_addr = (str(self.remote), self.remote_port)

        # Create a socket to use for the lifetime of the knock
        async with await asyncudp.create_socket(remote_addr=remote_addr) as socket:
            info, players = await self._get_info(socket)

        self.info = info
        self.players = players

        return info, players

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

    async def _get_info(self, socket: asyncudp.Socket, *, timeout: int | float = 5) -> Tuple[ServerInfo, List[PlayerInfo]]:
        timeout_at = datetime.now() + timedelta(seconds=timeout)

        # Collect data
        info = None
        players = []

        # Ask multiple times
        last_sent = None
        tries = 0

        while tries < self.tries:
            start_time = datetime.now()
            if timeout_at <= start_time:
                tries += 1
                continue
            timeout = (timeout_at - start_time).total_seconds()

            # Wait for remote's response.
            try:
                if last_sent is None or last_sent < tries:
                    last_sent = tries
                    buf = await self._ask(socket, timeout)
                else:
                    # Ride from the last ask request
                    buf, _ = await asyncio.wait_for(socket.recvfrom(), timeout)
            except TimeoutError:
                tries += 1
                continue

            try:
                res = Packet.unpack(buf)

                if isinstance(res, ServerInfoPacket):
                    info = res.info
                if isinstance(res, PlayerInfoPacket):
                    players.extend(p for p in res.players if not p.is_empty)
                    if info is not None and len(players) >= info.number_of_players:
                        # Escape early, we got the data we want
                        break
            except PacketError as err:
                logger.warning(f"Got error {err} knocking for server {self.remote}:{self.remote_port}")
                tries += 1

        if info is None or len(players) < info.number_of_players:
            raise ConnectError(f"Failed to get server info after {tries} tries")

        return info, players
