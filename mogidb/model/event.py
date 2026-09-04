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
    substitute: bool
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
    gathered_at: datetime | None = None

    def is_playing(self, user: User | str) -> bool:
        """
        Checks if a player is in the event and playing.

        A player is playing if they have a team assigned.
        """

        if isinstance(user, User):
            user_id = user.id
        else:
            user_id = user

        # A user cannot be playing in a LFG event
        if self.status == EventStatus.LFG:
            return False

        playing = {p.user.id for p in self.players if not p.substitute}
        return user_id in playing

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, src: Mapping[str, Any]) -> Self:
        from ..dacite import CONFIG
        return dacite.from_dict(cls, src, CONFIG)
    
