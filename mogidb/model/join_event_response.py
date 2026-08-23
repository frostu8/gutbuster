from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Self

import dacite

from .event import Event


@dataclass
class JoinEventResponse:
    """
    A response to a join request.

    Attributes:
        event: The event after the join.
        started: Whether the event was started by this join.
            When `True`, the status was automatically advanced to
            `EventStatus.ONGOING`.
    """

    event: Event
    started: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, src: Mapping) -> Self:
        from ..dacite import CONFIG
        return dacite.from_dict(cls, src, CONFIG)
