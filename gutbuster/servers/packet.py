from dataclasses import dataclass
from enum import Enum, Flag, unique
from typing import Optional, Dict, Self, Type, Any, List, Tuple
from abc import ABC, abstractmethod
import struct
from functools import reduce


RINGRACERS_VERSION = 2
MAX_PLAYERS = 16


class PacketError(Exception):
    def __init__(self, *args):
        super().__init__(*args)


class MissingHeaderError(PacketError):
    def __init__(self, *args):
        super().__init__(*args)


class BadChecksumError(PacketError):
    checksum: int

    def __init__(self, checksum: int, *args):
        super().__init__(*args)
        self.checksum = checksum


class PacketTypeError(PacketError):
    kind: int

    def __init__(self, kind: int, *args):
        super().__init__(*args)
        self.kind = kind


@unique
class RefuseReason(Enum):
    """
    Server refuse reasons.
    """

    OK = 0
    JOINS_DISABLED = 1
    FULL = 2


@unique
class GameSpeed(Enum):
    """
    Server gamespeeds.
    """

    EASY = 0  # Gear 1
    NORMAL = 1  # Gear 2
    HARD = 2  # Gear 3


@unique
class PacketType(Enum):
    ASKINFO = 12
    SERVERINFO = 13
    PLAYERINFO = 14
    TELLFILESNEEDED = 32
    MOREFILESNEEDED = 33


@unique
class ServerFlags(Flag):
    """
    Server flags.
    """

    LOTSOFADDONS = 0x20
    DEDICATED = 0x40
    VOICEENABLED = 0x80

    @classmethod
    def all(cls):
        return reduce(lambda x, acc: x | acc, (x for x in cls))


def strip_colors(input: str) -> str:
    codes = [
        "\\x80",
        "\\x81",
        "\\x82",
        "\\x83",
        "\\x84",
        "\\x85",
        "\\x86",
        "\\x87",
        "\\x88",
        "\\x89",
        "\\x8a",
        "\\x8b",
        "\\x8c",
        "\\x8d",
        "\\x8e",
        "\\x8f",
    ]
    for i in range(0x10):
        input = input.replace(codes[i], "")
    return input


@dataclass(kw_only=True)
class ServerInfo:
    """
    Ring racers server info.
    """

    # Server identification info
    application: str
    version: int
    subversion: int
    # Initial bytes of hash of commit
    commit: str

    # General game settings
    gametype_name: str
    server_name: str
    number_of_players: int
    max_players: int
    modified_game: bool
    cheats_enabled: bool
    avg_mobiums: int

    game_speed: GameSpeed
    flags: ServerFlags
    refuse_reason: RefuseReason

    # Current level things
    time: int
    level_time: int
    map_title: str
    map_md5: str
    actnum: int
    is_zone: bool

    # Addons
    number_of_files: int
    http_source: str


@dataclass(kw_only=True)
class PlayerInfo:
    """
    Ring Racers player info.
    """

    num: int
    name: str
    # Lets not. Ring Racers does not populate this (for good reason)
    # address: List[int]
    team: int
    score: int
    time_in_server: int

    # Skin is deprecated, always 0xff
    # skin: int
    # Supposed to be color, but also deprecated, always 0x0
    # data: int

    @property
    def is_empty(self) -> bool:
        return self.num == 255


# Taken from src/d_net.cpp, L:714
def net_checksum(packet: bytes, offset: int = 4) -> int:
    """
    Calculates the checksum of a packet.
    """

    checksum = 0x1234567
    length = len(packet) - offset  # exclude the checksum
    for i in range(length):
        checksum += ord(chr(packet[i + offset])) * (i + 1)
    return checksum


def _unpack(format: str, packet: bytes) -> Tuple[Dict[str, Any], bytes]:
    n = 0
    format_array = format.split("/")
    output = {}
    for data_format in format_array:
        unpack_param = ""
        unpack_param_len = 0
        for c in data_format:
            unpack_param += c
            unpack_param_len = unpack_param_len + 1
            if not c.isnumeric() and c != "*":
                break
        if "*" in unpack_param:
            unpack_param = str(len(packet) - n) + unpack_param[-1:]
        data = struct.unpack_from(unpack_param, packet, n)
        data_format_name = data_format[unpack_param_len:]

        if len(data) > 1:
            output[data_format_name] = list(data)
        else:
            output[data_format_name] = data[0]

        n += struct.calcsize(unpack_param)
    return output, packet[n:]


def cstrlen(s: bytes, offset: int = 0, n: Optional[int] = None) -> int:
    """
    Gets the length of a c-str.
    """

    length = len(s) - offset
    if length < 0:
        return 0

    # We can't substr outside of length.
    if n is not None and n < length:
        s = s[offset : offset + n]
        offset = 0
        length = n

    n = s.find(b"\0", offset)

    return length if n == -1 else n - offset + 1


def cstr(s: bytes, offset: int = 0, n: Optional[int] = None) -> str:
    """
    Gets the c-str.
    """

    n = cstrlen(s, offset, n)

    # Check that we haven't been truncated.
    if not ord(chr(s[offset + (n - 1)])):
        n = n - 1

    new_s = bytearray()
    for c in s:
        if c == 0x7F or c <= 0x19 or c >= 0x90:
            new_s.append(0x00)
        else:
            new_s.append(c)

    return (
        (new_s[offset : offset + n])
        .decode("utf-8", "backslashreplace")
        .replace("\x00", "")
    )


class Packet(ABC):
    """
    Ring Racers packet form.
    """

    _checksum: int

    @property
    def checksum(self) -> int:
        return self._checksum

    @classmethod
    @abstractmethod
    def packet_type(self) -> PacketType: ...

    @classmethod
    @abstractmethod
    def unpack_inner(cls, packet: bytes) -> Self: ...

    @abstractmethod
    def pack_inner(self) -> bytes: ...

    def pack(self) -> bytes:
        """
        Packs a Ring Racers packet.
        """

        # Ack unused, only used is type
        inner = self.pack_inner()
        buf = struct.pack("xxBx", self.__class__.packet_type().value) + inner

        # Calculate checksum
        checksum = net_checksum(buf, offset=0)
        return struct.pack("I", checksum) + buf

    @classmethod
    def unpack(cls, packet: bytes) -> Self:
        """
        Unpacks a Ring Racers packet.

        This verifies the packet before dispatching packet-specific handlers.
        """

        if len(packet) < 8:
            raise MissingHeaderError(f"Packet too short, len {len(packet)}")

        header = packet[:8]
        checksum = int.from_bytes(header[:4], byteorder="little", signed=False)

        if not checksum == net_checksum(packet):
            raise BadChecksumError(checksum, f"Bad checksum {checksum}")

        # We don't have to worry about ACK since Gutbuster only cares about
        # non-ackable packets.

        valid_packet_kinds = set(e.value for e in PacketType)

        packet_kind = ord(chr(packet[6]))
        if packet_kind not in valid_packet_kinds:
            raise PacketTypeError(packet_kind, f"Unknown packet type {packet_kind}")

        packet_kind = PacketType(packet_kind)

        # Deserialize based on packet type
        packet_cls = packet_types.get(packet_kind, None)
        if packet_cls is None:
            raise NotImplementedError("Packet kind not implemented")

        packet = packet_cls.unpack_inner(packet[8:])
        packet._checksum = checksum

        return packet


packet_types: Dict[PacketType, Type[Packet]] = {}


def packet(cls: Type[Packet]) -> Type[Packet]:
    packet_type = cls.packet_type()
    packet_types[packet_type] = cls
    return cls


@packet
class AskPacket(Packet):
    """
    Ring Racers ask info packet.
    """

    _packet_type = PacketType.ASKINFO

    version: int
    time: int

    def __init__(self, *, version: int = RINGRACERS_VERSION, time: int = 0):
        self.version = version
        self.time = 0

    @classmethod
    def packet_type(self) -> PacketType:
        return self._packet_type

    def pack_inner(self) -> bytes:
        return struct.pack("BI", self.version, self.time)

    @classmethod
    def unpack_inner(cls, packet: bytes) -> Packet:
        raise NotImplementedError()


@packet
class ServerInfoPacket(Packet):
    """
    Ring Racers server info packet.
    """

    _packet_type = PacketType.SERVERINFO
    _packet: str = (
        "B_255/"
        "Bpacketversion/"
        "16sapplication/"
        "Bversion/"
        "Bsubversion/"
        "4Bcommit/"
        "Bnumberofplayer/"
        "Bmaxplayer/"
        "Brefusereason/"
        "24sgametypename/"
        "Bmodifiedgame/"
        "Bcheatsenabled/"
        "Bkartvars/"
        "Bfileneedednum/"
        "Itime/"
        "Ileveltime/"
        "32sservername/"
        "33smaptitle/"
        "16smapmd5/"
        "Bactnum/"
        "Biszone/"
        "256shttpsource/"
        "Havgpwrlv/"  # Now Mobiums
        "*sfileneeded"
    )

    info: ServerInfo

    def __init__(self, info: ServerInfo):
        self.info = info

    @classmethod
    def packet_type(self) -> PacketType:
        return self._packet_type

    def pack_inner(self) -> bytes:
        raise NotImplementedError()

    @classmethod
    def unpack_inner(cls, packet: bytes) -> Packet:
        unpacked, _ = _unpack(cls._packet, packet)

        # Build server info struct
        # Calculate commit hash
        commit = ""
        for num in unpacked["commit"]:
            commit += f"{num:2x}"

        # Do kartvar stuff
        kartvars = unpacked["kartvars"]

        game_speed = GameSpeed(kartvars & 0x03)
        flags = ServerFlags(kartvars & ServerFlags.all().value)

        # Do strings
        application = cstr(unpacked["application"])
        gametypename = cstr(unpacked["gametypename"])
        servername = cstr(unpacked["servername"])
        maptitle = cstr(unpacked["maptitle"])
        httpsource = cstr(unpacked["httpsource"])

        # Calculate md5
        map_md5 = unpacked["mapmd5"].hex()

        info = ServerInfo(
            application=application,
            version=unpacked["version"],
            subversion=unpacked["subversion"],
            commit=commit,
            gametype_name=gametypename,
            server_name=servername,
            number_of_players=unpacked["numberofplayer"],
            max_players=unpacked["maxplayer"],
            modified_game=bool(unpacked["modifiedgame"]),
            cheats_enabled=bool(unpacked["cheatsenabled"]),
            avg_mobiums=unpacked["avgpwrlv"],
            game_speed=game_speed,
            flags=flags,
            refuse_reason=RefuseReason(unpacked["refusereason"]),
            time=unpacked["time"],
            level_time=unpacked["leveltime"],
            map_title=maptitle,
            map_md5=map_md5,
            actnum=unpacked["actnum"],
            is_zone=bool(unpacked["iszone"]),
            number_of_files=unpacked["fileneedednum"],
            http_source=httpsource,
        )

        return ServerInfoPacket(info)


@packet
class PlayerInfoPacket(Packet):
    """
    Ring Racers player info packet.
    """

    _packet_type = PacketType.PLAYERINFO
    _packet: str = "Bnum/22sname/4saddress/Bteam/Bskin/Bdata/Iscore/Htimeinserver"

    players: List[PlayerInfo]

    def __init__(self, *players: PlayerInfo):
        self.players = list(players)

    @classmethod
    def packet_type(self) -> PacketType:
        return self._packet_type

    def pack_inner(self) -> bytes:
        raise NotImplementedError()

    @classmethod
    def unpack_inner(cls, packet: bytes) -> Packet:
        players = []

        for i in range(MAX_PLAYERS):
            unpacked, packet = _unpack(cls._packet, packet)

            # Do strings
            name = cstr(unpacked["name"])

            players.append(PlayerInfo(
                num=unpacked["num"],
                name=name,
                team=unpacked["team"],
                score=unpacked["score"],
                time_in_server=unpacked["timeinserver"]
            ))

        return PlayerInfoPacket(*players)
