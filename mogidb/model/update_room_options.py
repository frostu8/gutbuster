from dataclasses import asdict, dataclass
from typing import Any

from ..types import UNSET, Unset
from .format_selection_mode import FormatSelectionMode


@dataclass
class UpdateRoomOptions:
    """
    Options for a room.

    This allows room options to be patched and unpatched.
    """

    players_required: int | None | Unset = UNSET
    max_players: int | None | Unset = UNSET
    format_selection_mode: FormatSelectionMode | None | Unset = UNSET
    votes_required: int | None | Unset = UNSET
    decay_after: int | None | Unset = UNSET
    inactivity_warning_after: int | None | Unset = UNSET
    inactivity_drop_after: int | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Remove UNSET items
        for key, item in d.items():
            if isinstance(item, Unset):
                d.pop(key)

        return d
