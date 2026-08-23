from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Self

import dacite

from ..types import UNSET, Unset
from .server import GameServer
from .team_mode import TeamMode


@dataclass
class EventFormat:
    """
    A single format for a event.

    Attributes:
        id (int): The id of the format.
        name (str): The human-readable name of the format.
        team_mode (TeamMode): The format team mode.
        servers (list[GameServer] | None): The allowed servers for the format.
    """

    id: int
    name: str
    team_mode: TeamMode
    servers: list[GameServer] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, src: Mapping[str, Any]) -> Self:
        from ..dacite import CONFIG
        return dacite.from_dict(cls, src, CONFIG)
    
