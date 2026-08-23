from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Self

import dacite

from ..types import UNSET, Unset
from .event_status import EventStatus
from .format import EventFormat
from .room import Room
from .server import GameServer
from .user import User


@dataclass
class EventParticipant:
    """
    A participant in an event.
    """

    user: User
    team_number: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, src: Mapping[str, Any]) -> Self:
        from ..dacite import CONFIG
        return dacite.from_dict(cls, src, CONFIG)


@dataclass
class Event:
    """
    An event in a room.
    """

    id: str
    status: EventStatus
    players: list[EventParticipant]
    created_at: datetime
    title: str | None
    format: EventFormat | None
    server: GameServer | None
    room: Room | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, src: Mapping[str, Any]) -> Self:
        from ..dacite import CONFIG
        return dacite.from_dict(cls, src, CONFIG)
    
