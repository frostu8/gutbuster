import datetime
import string
import random
import logging
from typing import Optional, List
from gutbuster.room import Room
from gutbuster.user import User, Rating
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)


class Participant(object):
    """
    A single participant in a mogi.

    This also stores the user's rating at the time of JOINING the mogi.
    """

    id: int
    event_id: int
    user_id: int
    rating: Optional[Rating]
    score: Optional[int]
    inserted_at: datetime.datetime
    updated_at: datetime.datetime

    def __init__(
        self,
        *,
        id: int,
        event_id: int,
        user_id: int,
        rating: Optional[Rating] = None,
        score: Optional[int] = None,
        inserted_at: datetime.datetime,
        updated_at: datetime.datetime,
    ):
        self.id = id
        self.event_id = event_id
        self.user_id = user_id
        self.rating = rating
        self.score = score
        self.inserted_at = inserted_at
        self.updated_at = updated_at


class Event(object):
    """
    An event, or a "mogi."
    """

    id: int
    short_id: str
    room: Room
    participants: Optional[List[Participant]]
    active: bool
    inserted_at: datetime.datetime
    updated_at: datetime.datetime

    def __init__(
        self,
        *,
        id: int,
        short_id: str,
        room: Room,
        active: bool,
        participants: Optional[List[Participant]] = None,
        inserted_at: datetime.datetime,
        updated_at: datetime.datetime,
    ):
        self.id = id
        self.short_id = short_id
        self.room = room
        self.active = active
        self.participants = participants
        self.inserted_at = inserted_at
        self.updated_at = updated_at

    async def preload_participants(self, conn: AsyncConnection):
        """
        Preloads participants.

        By default, the database won't automatically fetch the participants in
        an event. This function asks for the list, populating the
        `self.participants` value.
        """

        res = await conn.execute(
            text("""
            WITH recent_ratings AS (
                SELECT r1.user_id, r1.rating, r1.deviation
                FROM rating r1, rating r2
                WHERE r2.inserted_at <= :inserted_at
                GROUP BY r1.user_id, r1.inserted_at, r1.rating, r1.deviation
                HAVING r1.inserted_at = MAX(r2.inserted_at)
            )
            SELECT
                r.rating,
                r.deviation,
                p.id,
                p.user_id,
                p.score,
                p.inserted_at,
                p.updated_at
            FROM participant p
            LEFT OUTER JOIN recent_ratings r
            ON r.user_id = p.user_id
            WHERE p.event_id = :event_id
            """),
            {"event_id": self.id, "inserted_at": self.inserted_at.isoformat()},
        )

        self.participants = []
        for row in res:
            participant = Participant(
                id=row.id,
                event_id=self.id,
                user_id=row.user_id,
                rating=Rating(row.rating, row.deviation, user_id=row.user_id),
                score=row.score,
                inserted_at=datetime.datetime.fromisoformat(row.inserted_at),
                updated_at=datetime.datetime.fromisoformat(row.updated_at),
            )
            self.participants.append(participant)

    def get_participants(self) -> List[Participant]:
        """
        Returns the list of participants.

        Returns an empty list if the participants isn't preloaded.
        """
        return self.participants or []

    def has(self, user: User):
        """
        Checks if a user is in this event.

        Raises `ValueError` if the participants are not preloaded
        """

        if self.participants is None:
            raise ValueError("participants not preloaded")

        return next((True for p in self.participants if p.id == user.id), False)

    async def join(self, user: User, conn: AsyncConnection) -> Participant:
        """
        Adds a participant to an event.

        Raises an error if the user is already a part of the event.
        """

        now = datetime.datetime.now()

        res = await conn.execute(
            text("""
            INSERT INTO participant (user_id, event_id, inserted_at, updated_at)
            VALUES (:user_id, :event_id, :now, :now)
            RETURNING id
            """),
            {"user_id": user.id, "event_id": self.id, "now": now.isoformat()},
        )

        row = res.first()
        if row is None:
            raise ValueError("failed to get id of new row")

        participant = Participant(
            id=row.id,
            event_id=self.id,
            user_id=user.id,
            rating=user.rating,
            inserted_at=now,
            updated_at=now,
        )

        if self.participants is not None:
            self.participants.append(participant)

        return participant

    async def leave(self, user: User, conn: AsyncConnection) -> None:
        """
        Removes a user from an event.

        Raises an error if the user is not a part of the event.
        """

        res = await conn.execute(
            text("""
            DELETE FROM participant
            WHERE
                user_id = :user_id
                AND event_id = :event_id
            """),
            {"user_id": user.id, "event_id": self.id},
        )

        if res.rowcount > 0:
            if self.participants is not None:
                self.participants = [p for p in self.participants if not p.user_id == user.id]
        else:
            raise ValueError("cannot remove user that isn't participating")


def _generate_id(length: int) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


async def create_event(room: Room, conn: AsyncConnection) -> Event:
    """
    Creates an active event in a room with default settings.
    """

    now = datetime.datetime.now()
    now_serialized = now.isoformat()

    # To generate a unique short id, we simply do rejection sampling (generate
    # a random id, if it exists generate another one)
    event = None
    while event is None:
        try:
            short_id = _generate_id(8)
            res = await conn.execute(
                text("""
                INSERT INTO event (short_id, room_id, inserted_at, updated_at)
                VALUES (:short_id, :room_id, :now, :now)
                RETURNING id
                """),
                {"short_id": short_id, "room_id": room.id, "now": now_serialized},
            )

            row = res.first()
            if row is None:
                raise ValueError("failed to get row id")

            event = Event(
                id=row.id,
                short_id=short_id,
                room=room,
                active=True,
                inserted_at=now,
                updated_at=now,
            )
        except IntegrityError as e:
            # Try to generate another id...
            logger.warning(e)
            pass

    return event


async def get_latest_active_event(room: Room, conn: AsyncConnection) -> Optional[Event]:
    """
    Gets the latest currently active event in a room.
    """

    res = await conn.execute(
        text("""
        SELECT id, short_id, active, inserted_at, updated_at
        FROM event
        WHERE room_id = :room_id AND active
        ORDER BY inserted_at DESC
        LIMIT 1
        """),
        {"room_id": room.id},
    )

    row = res.first()
    if row is None:
        return None

    inserted_at = datetime.datetime.fromisoformat(row.inserted_at)
    updated_at = datetime.datetime.fromisoformat(row.updated_at)

    return Event(
        id=row.id,
        short_id=row.short_id,
        room=room,
        active=row.active,
        inserted_at=inserted_at,
        updated_at=updated_at,
    )
