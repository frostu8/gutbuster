import discord
from discord import app_commands

import mogidb
from bot.app import Module
from mogidb.model import Room


class NotificationQueue:
    """
    A queue of users wishing to be notified for the next event.
    """

    queues: dict[int, list[discord.Member | discord.User]]

    def __init__(self):
        self.queues = {}

    def insert(self, room: Room, user: discord.Member | discord.User):
        """
        Adds a user to the notification queue.
        """

        if room.id in self.queues:
            queue = self.queues[room.id]

            # Throw an error if the user already exists
            if any(u.id == user.id for u in queue):
                raise ValueError(f"user {user.id} exists in the queue")

            queue.append(user)
        else:
            self.queues[room.id] = [user]

    def remove(self, room: Room, user: discord.Member | discord.User):
        """
        Removes a user from the notification queue.
        """

        if room.id in self.queues:
            queue = self.queues[room.id]
        else:
            queue = []

        # Throw an error if the user does not exist in the queue
        if all(u.id != user.id for u in queue):
            raise ValueError(f"user {user.id} does not exist in the queue")

        self.queues[room.id] = [u for u in queue if u.id != user.id]

    def drain(self, room: Room) -> list[discord.Member | discord.User]:
        """
        Drains all the users looking to be notified in a queue.

        This does not fail; if there are no users queued, it will simply return
        an empty list and leave the queue unmodified.
        """

        if room.id in self.queues:
            queue = self.queues[room.id]
            del self.queues[room.id]
            return queue
        else:
            return []
        


class NotifyModule(Module):
    """
    The bot notification module.

    Contains the /notifyme command.
    """

    client: discord.Client
    db: mogidb.Client

    _queue: NotificationQueue

    def __init__(self, client: discord.Client, db: mogidb.Client, *, queue: NotificationQueue | None = None):
        self.client = client
        self.db = db

        if queue is None:
            self._queue = NotificationQueue()
        else:
            self._queue = queue

    @property
    def queue(self) -> NotificationQueue:
        return self._queue

    @app_commands.command(name="notifyme", description="Notify when the next queue starts")
    async def command_notifyme(self, interaction: discord.Interaction):
        """
        The /notifyme command.
        """

        assert interaction.guild
        assert isinstance(interaction.channel, discord.TextChannel), "Command not called in a guild context"

        user = interaction.user
        channel = interaction.channel

        # Check if we can even have events here
        room = await self.db.get_room(interaction.guild.id, channel.id)
        if room is None:
            await interaction.response.send_message(
                "This channel isn't setup for mogis!",
                ephemeral=True,
            )
            return

        # Add user to the queue
        try:
            self.queue.insert(room, user)
        except ValueError:
            # User already in the queue
            pass

        await interaction.response.send_message(
            f"{user.name} will be notified when the next mogi starts.",
        )

    @app_commands.command(name="unnotifyme", description="Disables notification for when the next queue starts")
    async def command_unnotifyme(self, interaction: discord.Interaction):
        """
        The /unnotifyme command.
        """

        assert interaction.guild
        assert isinstance(interaction.channel, discord.TextChannel), "Command not called in a guild context"

        user = interaction.user
        channel = interaction.channel

        # Check if we can even have events here
        room = await self.db.get_room(interaction.guild.id, channel.id)
        if room is None:
            await interaction.response.send_message(
                "This channel isn't setup for mogis!",
                ephemeral=True,
            )
            return

        # Remove user from the queue
        try:
            self.queue.remove(room, user)
        except ValueError:
            # User not in the queue
            pass

        await interaction.response.send_message(
            f"{user.name} will *not* be notified when the next mogi starts.",
        )
