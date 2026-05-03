from sqlalchemy.sql import text
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncConnection
from dataclasses import dataclass, field
from enum import unique, Enum
from .server import Server


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

    async def find_server(self, conn: AsyncConnection) -> Optional[Server]:
        """
        Finds an available server to host the event.

        This automatically updates the event's remote with the server, and
        returns the found server.
        """

        res = await conn.execute(
            text("""
            SELECT s.*
            FROM event_format ef, event_format_server relation, server s
            WHERE
                ef.id = relation.event_format_id
                AND s.id = relation.server_id
                AND ef.id = :format_id
                AND s.remote NOT IN (
                    SELECT s.remote
                    FROM server s, event e
                    WHERE
                    e.remote = s.remote
                    AND (e.status = 0 OR e.status = 1)
                )
            ORDER BY s.inserted_at ASC
            LIMIT 1
            """),
            {"format_id": self.id}
        )

        row = res.first()
        if row is None:
            return None
        
        return Server(
            id=row.id,
            discord_guild_id=row.discord_guild_id,
            remote=row.remote,
            label=row.label,
            inserted_at=row.inserted_at,
            updated_at=row.updated_at,
        )

