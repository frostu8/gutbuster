import datetime
import string
import random
import logging
from typing import Optional
from gutbuster.room import Room
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)


class Event(object):
    """
    An event, or a "mogi."
    """

    id: int
    short_id: str
    room: Room
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
        inserted_at: datetime.datetime,
        updated_at: datetime.datetime,
    ):
        self.id = id
        self.short_id = short_id
        self.room = room
        self.active = active
        self.inserted_at = inserted_at
        self.updated_at = updated_at


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


async def get_latest_active_event(
    room: Room, conn: AsyncConnection
) -> Optional[Event]:
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
