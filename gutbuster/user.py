from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
import discord
from dataclasses import dataclass, field
import datetime


type Member = discord.User | discord.Member


# Every fiber in my body tells me this is very bad and is going to cause a Fuck
# Ton Of Problems when the codebase gets more complicated but, as they say,
# when in Rome, do as the Romans do.
# class RatedUser(User):
# Nope, nevermind. I am too much of a pussy. I am not strong enough for the
# miseries of OOP. Not built for these streets.
@dataclass(kw_only=True)
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


@dataclass(kw_only=True)
class User(object):
    """
    A Gutbuster user.

    Stores some information about the user, most importantly: their rating.
    """

    id: int
    user: Member | discord.Object
    name: str
    rating: Rating | None = field(default=None)
    inserted_at: datetime.datetime
    updated_at: datetime.datetime

    async def fetch_user(self, app: discord.Client) -> Member:
        """
        Fetches the Discord user associated with this user.
        """

        if isinstance(self.user, discord.User | discord.Member):
            return self.user
        else:
            discord_user = app.get_user(self.user.id)
            if discord_user is None:
                # Fetch from the API instead
                discord_user = await app.fetch_user(self.user.id)
            self.user = discord_user
            return self.user


async def get_user(discord_user: Member, conn: AsyncConnection) -> User | None:
    # Try to find the user if they exist
    res = await conn.execute(
        text("""
        SELECT u.id, u.name, r.rating, r.deviation, u.inserted_at, u.updated_at
        FROM user u
        LEFT OUTER JOIN rating r
        ON u.id = r.user_id
        WHERE u.discord_user_id = :id
        ORDER BY r.inserted_at DESC
        LIMIT 1
        """),
        {"id": discord_user.id},
    )

    row = res.first()
    if row is None:
        return None

    # Load information about the user
    id = row.id
    inserted_at = datetime.datetime.fromisoformat(row.inserted_at)
    updated_at = datetime.datetime.fromisoformat(row.updated_at)

    # Check if the username is stale
    name = row.name
    if not row.name == discord_user.name:
        now = datetime.datetime.now()
        await conn.execute(
            text("""
            UPDATE user
            SET name = :name
            WHERE id = :id, updated_at = :now
            """),
            {"id": id, "name": discord_user.name, "now": now.isoformat()},
        )

        name = discord_user.name

    if row.rating is None or row.deviation is None:
        # This user is unrated...
        return User(
            id=id,
            user=discord_user,
            name=name,
            inserted_at=inserted_at,
            updated_at=updated_at,
        )
    else:
        # This user is rated!
        return User(
            id=id,
            user=discord_user,
            name=name,
            rating=Rating(row.rating, row.deviation, user_id=id),
            inserted_at=inserted_at,
            updated_at=updated_at,
        )


async def get_or_create_user(discord_user: Member, conn: AsyncConnection) -> User:
    """
    Gets a user from the database.

    If the user cannot be found, initializes their user data with basic info.
    """

    # Try to find the user if they exist
    user = await get_user(discord_user, conn)
    if user is not None:
        return user

    # Create the missing user
    now = datetime.datetime.now()
    name = discord_user.name

    # Insert into database
    res = await conn.execute(
        text("""
        INSERT INTO user (discord_user_id, name, inserted_at, updated_at)
        VALUES (:id, :name, :now, :now)
        RETURNING id
        """),
        {"id": discord_user.id, "name": name, "now": now.isoformat()},
    )

    row = res.first()
    if row is None:
        raise ValueError("failed to get id of inserted row")

    user = User(
        id=row.id, user=discord_user, name=name, inserted_at=now, updated_at=now
    )

    return user
