from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Self

import dacite
from dacite import Config

from .format_selection_mode import FormatSelectionMode


@dataclass
class RoomOptions:
    """
    Options for a room.
    """

    players_required: int | None = None
    max_players: int | None = None
    format_selection_mode: FormatSelectionMode | None = None
    votes_required: int | None = None
    decay_after: int | None = None
    inactivity_warning_after: int | None = None
    inactivity_drop_after: int | None = None

    def merge(self, other: RoomOptions) -> RoomOptions:
        """
        Merges a set of configurations with overrides, taking values from
        `other` first before filling from self.
        """

        # Time for trolling
        d = self.to_dict()
        d |= {k: v for k, v in other.to_dict().items() if v is not None}
        return RoomOptions.from_dict(d)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, src: Mapping[str, Any]) -> Self:
        return dacite.from_dict(cls, src, Config(cast=[FormatSelectionMode]))
