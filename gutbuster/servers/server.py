from .packet import ServerInfo, Packet, ServerInfoPacket, AskPacket, strip_colors
from typing import Optional
import asyncudp
import asyncio
import ipaddress
from datetime import datetime


class Server:
    """
    A Ring Racers server.
    """

    remote: ipaddress.IPv4Address | ipaddress.IPv6Address
    remote_port: int
    tries: int

    label: Optional[str]

    info: Optional[ServerInfo]
    ping: Optional[int]

    _server_name: Optional[str]

    def __init__(self, remote: str, *, label: Optional[str] = None, tries: int = 5):
        ip, separator, port = remote.rpartition(':')
        assert separator

        self.remote = ipaddress.ip_address(ip)
        self.remote_port = int(port)
        self.tries = tries

        self.label = label

        self.info = None
        self.ping = None
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

    async def knock(self) -> ServerInfo:
        """
        Asks for a ``ServerInfo`` frm the remote.
        """

        remote_addr = (str(self.remote), self.remote_port)

        # Create a socket to use for the lifetime of the knock
        async with await asyncudp.create_socket(remote_addr=remote_addr) as socket:
            info = await self._get_info(socket)

        self.info = info
        return info

    async def _get_info(self, socket: asyncudp.Socket) -> ServerInfo:
        # Creates an ask packet.
        packet = AskPacket().pack()

        # Ask multiple times
        tries = 0

        while tries < self.tries:
            # Send to remote
            start_time = datetime.now()
            socket.sendto(packet)

            # Wait for remote's response.
            buf, addr = await asyncio.wait_for(socket.recvfrom(), 5)
            end_time = datetime.now()

            # Update ping
            self.ping = (end_time - start_time).total_seconds() * 1000

            # Ignore packets that are too small
            if buf is not None and len(buf) > 8:
                res = Packet.unpack(buf)

                if isinstance(res, ServerInfoPacket):
                    return res.info

            tries = tries + 1

        raise ValueError(f"Failed to get server info after {tries} tries")
