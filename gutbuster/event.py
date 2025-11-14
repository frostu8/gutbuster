import datetime
import string
import random
import logging
import discord
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List
from gutbuster.room import Room
from gutbuster.user import User, Rating
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)


class EventStatus(Enum):
    LFG = 0
    STARTED = 1
    ENDED = 2


@dataclass(kw_only=True)
class Participant(object):
    """
    A single participant in a mogi.

    This also stores the user's rating at the time of JOINING the mogi.
    """

    id: int
    event_id: int
    user: User
    rating: Optional[Rating]
    score: Optional[int] = field(default=None)
    inserted_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(kw_only=True)
class Event(object):
    """
    An event, or a "mogi."
    """

    id: int
    short_id: str
    room: Room
    participants: Optional[List[Participant]] = field(default=None)
    status: EventStatus = field(default=EventStatus.LFG)
    inserted_at: datetime.datetime
    updated_at: datetime.datetime

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
                SELECT r1.id, r1.user_id, r1.rating, r1.deviation
                FROM rating r1, rating r2
                WHERE r2.inserted_at <= :inserted_at
                GROUP BY r1.id, r1.user_id, r1.inserted_at, r1.rating, r1.deviation
                HAVING r1.inserted_at = MAX(r2.inserted_at)
            )
            SELECT
                r.id AS rating_id,
                r.rating,
                r.deviation,
                p.id,
                p.user_id,
                p.score,
                p.inserted_at,
                p.updated_at,
                u.name,
                u.discord_user_id,
                u.inserted_at AS user_inserted_at,
                u.updated_at AS user_updated_at
            FROM participant p, user u
            LEFT OUTER JOIN recent_ratings r
            ON r.user_id = p.user_id
            WHERE
                p.user_id = u.id
                AND p.event_id = :event_id
            """),
            {"event_id": self.id, "inserted_at": self.inserted_at.isoformat()},
        )

        self.participants = []
        for row in res:
            user = User(
                id=row.user_id,
                user=discord.Object(row.discord_user_id),
                name=row.name,
                inserted_at=datetime.datetime.fromisoformat(row.user_inserted_at),
                updated_at=datetime.datetime.fromisoformat(row.user_updated_at),
            )
            participant = Participant(
                id=row.id,
                event_id=self.id,
                user=user,
                rating=Rating(
                    row.rating, row.deviation, id=row.rating_id, user_id=row.user_id
                ),
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

        return any(p.user.id == user.id for p in self.participants)

    def is_active(self) -> bool:
        """
        Checks if the event is active
        """
        return self.status == EventStatus.LFG or self.status == EventStatus.STARTED

    async def set_status(self, status: EventStatus, conn: AsyncConnection) -> None:
        """
        Changes the event status.
        """

        now = datetime.datetime.now()
        await conn.execute(
            text("""
            UPDATE event
            SET status = :status, updated_at = :now
            WHERE id = :event_id
            """),
            {"event_id": self.id, "now": now.isoformat(), "status": status.value},
        )

        self.status = status

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
            user=user,
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
                self.participants = [
                    p for p in self.participants if not p.user.id == user.id
                ]
        else:
            raise ValueError("cannot remove user that isn't participating")

    async def delete(self, conn: AsyncConnection) -> None:
        """
        Deletes an event.

        The event is now invalidated after this call.
        """

        await conn.execute(
            text("""
            DELETE FROM event
            WHERE id = :id
            """),
            {"id": self.id},
        )


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
                inserted_at=now,
                updated_at=now,
            )
        except IntegrityError as e:
            # Try to generate another id...
            logger.warning(e)
            pass

    await event.preload_participants(conn)
    return event


async def get_latest_active_event(room: Room, conn: AsyncConnection) -> Optional[Event]:
    """
    Gets the latest currently active event in a room.
    """

    res = await conn.execute(
        text("""
        SELECT id, short_id, status, inserted_at, updated_at
        FROM event
        WHERE
            room_id = :room_id
            AND (status = 0 OR status = 1)
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

    event = Event(
        id=row.id,
        short_id=row.short_id,
        room=room,
        status=EventStatus(row.status),
        inserted_at=inserted_at,
        updated_at=updated_at,
    )

    await event.preload_participants(conn)
    return event
