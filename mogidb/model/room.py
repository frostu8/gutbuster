from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Self

import dacite

from ..types import UNSET, Unset
from .format import EventFormat
from .guild import Guild
from .room_options import RoomOptions


@dataclass
class Room:
    """
    A mogi room, which may have many events.
    """

    id: int
    name: str
    enabled: bool
    settings: RoomOptions
    created_at: datetime
    updated_at: datetime
    formats: list[EventFormat] | Unset = UNSET
    guild: Guild | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, src: Mapping[str, Any]) -> Self:
        from ..dacite import CONFIG
        return dacite.from_dict(cls, src, CONFIG)
    
    
