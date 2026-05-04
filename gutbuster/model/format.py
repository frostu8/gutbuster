from datetime import datetime
import discord
from sqlalchemy.sql import text
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncConnection
from dataclasses import dataclass, field
from enum import unique, Enum


@unique
class FormatSelectMode(Enum):
    """
    How to select formats in an event.
    """
    VOTE = 0
    RANDOM = 1


@unique
class TeamMode(Enum):
    """
    How to assign teams to players after the mogi has gathered.
    """
    FREE_FOR_ALL = 0
    TWO_TEAMS = 2
    THREE_TEAMS = 3
    FOUR_TEAMS = 4

    def has_equal_teams(self, player_count: int) -> bool:
        """
        Given a player count `player_count`, will the teams have equal players?
        Returs `true` if they will have equal players.
        """

        match self:
            case TeamMode.FREE_FOR_ALL:
                # Free for all will always have equal teams
                return True
            case (
                TeamMode.TWO_TEAMS
                | TeamMode.THREE_TEAMS
                | TeamMode.FOUR_TEAMS
            ):
                team_count = self.value
                return player_count % team_count == 0
            case _:
                return False


@dataclass
class EventFormat(object):
    """
    An event format
    """

    id: int
    name: str = field(kw_only=True)
    team_mode: TeamMode = field(kw_only=True)
