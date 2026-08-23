import datetime
from typing import Protocol, Self

import dacite

from .model import (
    FormatSelectionMode,
    GameSpeed,
    Guild,
    ServerFlags,
    TeamMode,
    UserFlags,
)

CONFIG = dacite.Config(
    forward_references={"Guild": Guild},
    cast=[FormatSelectionMode, TeamMode, GameSpeed, ServerFlags, UserFlags],
    type_hooks={datetime.datetime: datetime.datetime.fromisoformat}
)

class FromDict(Protocol):
    @classmethod
    def from_dict(cls, data: dict) -> Self:
        ...
