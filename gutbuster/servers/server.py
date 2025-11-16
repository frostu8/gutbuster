from .packet import ServerInfo, Packet, ServerInfoPacket, AskPacket
from typing import Optional
import asyncudp
import asyncio
import ipaddress


class Server:
    """
    A Ring Racers server.
    """

    remote: ipaddress.IPv4Address | ipaddress.IPv6Address
    remote_port: int
    tries: int

    label: Optional[str]

    def __init__(self, remote: str, *, label: Optional[str], tries: int = 5):
        ip, separator, port = remote.rpartition(':')
        assert separator

        self.remote = ipaddress.ip_address(ip)
        self.remote_port = int(port)
        self.tries = tries

        self.label = label

    async def knock(self) -> ServerInfo:
        """
        Asks for a ``ServerInfo`` frm the remote.
        """

        remote_addr = (str(self.remote), self.remote_port)
        # Create a socket to use for the lifetime of the knock
        socket = await asyncudp.create_socket(remote_addr=remote_addr)

        return await self._get_info(socket)

    async def _get_info(self, socket: asyncudp.Socket) -> ServerInfo:
        # Creates an ask packet.
        packet = AskPacket().pack()

        # Ask multiple times
        tries = 0

        while tries < self.tries:
            # Send to remote
            socket.sendto(packet)

            # Wait for remote's response.
            buf, addr = await asyncio.wait_for(socket.recvfrom(), 5)
            # Ignore packets that are too small
            if buf is not None and len(buf) > 8:
                res = Packet.unpack(buf)

                if isinstance(res, ServerInfoPacket):
                    return res.info

            tries = tries + 1

        raise ValueError(f"Failed to get server info after {tries} tries")
