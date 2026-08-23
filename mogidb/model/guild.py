from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Self

import dacite

from ..types import UNSET, Unset
from .room_options import RoomOptions
from .server import GameServer


@dataclass
class Guild:
    """
    A guild.
    """

    id: int
    settings: RoomOptions
    servers: list[GameServer] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, src: Mapping[str, Any]) -> Self:
        from ..dacite import CONFIG
        return dacite.from_dict(cls, src, CONFIG)

