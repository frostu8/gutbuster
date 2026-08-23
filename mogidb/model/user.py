from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Self

import dacite

from .user_flags import UserFlags


@dataclass
class User:
    """
    A user.

    Attributes:
        id (str): The short ID of the user.
    """

    id: str
    display_name: str
    flags: UserFlags
    discord_user_id: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, src: Mapping[str, Any]) -> Self:
        from ..dacite import CONFIG
        return dacite.from_dict(cls, src, CONFIG)
