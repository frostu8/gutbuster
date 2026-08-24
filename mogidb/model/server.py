from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Self

import dacite

from ..types import UNSET, Unset
from .game_speed import GameSpeed
from .server_flags import ServerFlags

if TYPE_CHECKING:
    from .guild import Guild


@dataclass
class PlayerInfo:
    """
    Information about a player in a server.
    """

    name: str
    num: int
    score: int
    team: int
    time_in_server: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, src: Mapping[str, Any]) -> Self:
        from ..dacite import CONFIG
        return dacite.from_dict(cls, src, CONFIG)


@dataclass
class ServerInfo:
    """
    Information about a running server.

    Attributes:
        avg_mobiums (int): The average skill level of the lobby.
        cheats_enabled (bool): `true` if cheats are on.
        flags (ServerFlags): Server flags.
        game_speed (GameSpeed): Game speed.
        gametype_name (str): The gametype of the server.
        http_source (str): The server's HTTP source for addons.
        level_time (int): The time (in tics) the server has been in the current map.
        map_md5 (str): The map's MD5 hash.
        map_name (str): The name of the map.
        max_players (int): Maximum player count.
        modified_game (bool): `true` if the game has addons.
        players (list[PlayerInfo]): The players in the server.
        server_name (str): The name of the server, with colors removed.
        time (int): The time (in tics) the server has been running.
    """

    avg_mobiums: int
    cheats_enabled: bool
    flags: ServerFlags
    game_speed: GameSpeed
    gametype_name: str
    http_source: str
    level_time: int
    map_md5: str
    map_name: str
    max_players: int
    modified_game: bool
    players: list[PlayerInfo]
    server_name: str
    time: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, src: Mapping[str, Any]) -> Self:
        from ..dacite import CONFIG
        return dacite.from_dict(cls, src, CONFIG)


@dataclass
class GameServer:
    """
    A game server.
    """

    id: int
    remote: str
    label: str
    note: str | None
    info: ServerInfo | None
    last_update_time: datetime | None
    guild: "Guild | Unset" = UNSET  # noqa: UP037

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, src: Mapping[str, Any]) -> Self:
        from ..dacite import CONFIG
        return dacite.from_dict(cls, src, CONFIG)

    
