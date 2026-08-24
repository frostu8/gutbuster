from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Self

import dacite

from ..types import UNSET, Unset
from .format import EventFormat
from .format_selection_mode import FormatSelectionMode
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

    def _settings(self) -> RoomOptions:
        if isinstance(self.guild, Guild):
            return self.guild.settings.merge(self.settings)
        else:
            return self.settings

    @property
    def decay_after(self) -> int:
        settings = self._settings()
        if settings.decay_after is not None:
            return settings.decay_after
        else:
            return 3000

    @property
    def format_selection_mode(self) -> FormatSelectionMode:
        settings = self._settings()
        if settings.format_selection_mode is not None:
            return settings.format_selection_mode
        else:
            return FormatSelectionMode.RANDOM

    @property
    def inactivity_warning_after(self) -> int:
        settings = self._settings()
        if settings.inactivity_warning_after is not None:
            return settings.inactivity_warning_after
        else:
            return 1500

    @property
    def inactivity_drop_after(self) -> int:
        settings = self._settings()
        if settings.inactivity_drop_after is not None:
            return settings.inactivity_drop_after
        else:
            return 2100

    @property
    def max_players(self) -> int:
        settings = self._settings()
        if settings.max_players is not None:
            return settings.max_players
        else:
            return 12

    @property
    def players_required(self) -> int:
        settings = self._settings()
        if settings.players_required is not None:
            return settings.players_required
        else:
            return 8

    @property
    def votes_required(self) -> int:
        settings = self._settings()
        if settings.votes_required is not None:
            return settings.votes_required
        else:
            return 4

    @property
    def role_whitelist(self) -> list[int]:
        settings = self._settings()
        if settings.role_whitelist is not None:
            return settings.role_whitelist
        else:
            return []

    @property
    def role_blacklist(self) -> list[int]:
        settings = self._settings()
        if settings.role_blacklist is not None:
            return settings.role_blacklist
        else:
            return []
    
    
