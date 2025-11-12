from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
import discord
import datetime


# Every fiber in my body tells me this is very bad and is going to cause a Fuck
# Ton Of Problems when the codebase gets more complicated but, as they say,
# when in Rome, do as the Romans do.
# class RatedUser(User):
# Nope, nevermind. I am too much of a pussy. I am not strong enough for the
# miseries of OOP. Not built for these streets.
class Rating(object):
    """
    A user's rating.
    """

    user_id: int
    rating: float
    deviation: float

    def __init__(
        self,
        rating: float,
        deviation: float,
        *,
        user_id: int,
    ):
        self.user_id = user_id
        self.rating = rating
        self.deviation = deviation


class User(object):
    """
    A Gutbuster user.

    Stores some information about the user, most importantly: their rating.
    """

    id: int | None
    user: discord.Object
    rating: Rating | None
    inserted_at: datetime.datetime
    updated_at: datetime.datetime

    def __init__(
        self,
        *,
        id: int | None = None,
        user: discord.Object,
        rating: Rating | None = None,
        inserted_at: datetime.datetime,
        updated_at: datetime.datetime,
    ):
        self.id = id
        self.user = user
        self.rating = rating
        self.inserted_at = inserted_at
        self.updated_at = updated_at


async def get_or_init_user(discord_user: discord.Object, conn: AsyncConnection) -> User:
    """
    Gets a user from the database.

    If the user cannot be found, initializes their user data with basic info.
    """

    # Try to find the user if they exist
    res = await conn.execute(
        text("""
        SELECT u.id, r.rating, r.deviation, u.inserted_at, u.updated_at
        FROM user u, rating r
        WHERE
            u.id = r.user_id
            AND u.discord_user_id = :id
        """),
        {"id": discord_user.id},
    )

    row = res.first()
    if row is None:
        # Create the missing user
        now = datetime.datetime.now()
        user = User(user=discord_user, inserted_at=now, updated_at=now)

        # Insert into database
        await conn.execute(
            text("""
            INSERT INTO user (discord_user_id, inserted_at, updated_at)
            VALUES (:id, :now, :now)
            """),
            {"id": discord_user.id, "now": now.isoformat()},
        )

        return user
    else:
        # Load information about the user
        id = row.id
        inserted_at = datetime.datetime.fromisoformat(row.inserted_at)
        updated_at = datetime.datetime.fromisoformat(row.updated_at)

        if row.rating is None or row.deviation is None:
            # This user is unrated...
            return User(
                id=id, user=discord_user, inserted_at=inserted_at, updated_at=updated_at
            )
        else:
            # This user is rated!
            return User(
                id=id,
                user=discord_user,
                rating=Rating(row.rating, row.deviation, user_id=id),
                inserted_at=inserted_at,
                updated_at=updated_at,
            )
