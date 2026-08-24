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

    Attributes:
        players_required: The amount of players needed to start an event.
        max_players: The amount of players allowed in an event.
        format_selection_mode: The mode for format selection.
        votes_required: The amount of votes needed for a format to be
            selected before time is up.
        decay_after: The amount of time it takes for events to decay, in
            seconds. When an event decays, it can be ended before the event
            starts.
        inactivity_warning_after: The amount of time before the bot warns
            someone for inactivity, in seconds.
        inactivity_drop_after: The amount of time before the bot drops
            someone for inactivity, in seconds.
        role_whitelist: The roles to allow in the queue.

            By default, this is empty and does nothing. When there are roles
            here, **only** members with at least one role in this list are
            allowed to /c in the room.

            When this is set, the bot will tag the roles instead of @here
            when reaching queue milestones or when /ping is sent
        role_blacklist: The roles to disallow in the queue.

            By default, this is empty. Members with *any* of these roles are
            not permitted to /c in the room.
    """

    players_required: int | None = None
    max_players: int | None = None
    format_selection_mode: FormatSelectionMode | None = None
    votes_required: int | None = None
    decay_after: int | None = None
    inactivity_warning_after: int | None = None
    inactivity_drop_after: int | None = None
    role_whitelist: list[int] | None = None
    role_blacklist: list[int] | None = None

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
