import asyncio
from asyncio import Task
from datetime import datetime, timedelta
import inspect
from typing import Optional, Awaitable, List, Dict
import discord
from gutbuster.app import Module
from discord import ui, AllowedMentions


class StickyView(ui.LayoutView):
    """
    A sticky view.
    """

    message: Optional[discord.Message]
    last_message: Optional[datetime]
    cooldown: timedelta

    _event: Optional[asyncio.Event]
    _task: Optional[Task[None]]

    allowed_mentions: AllowedMentions

    def __init__(self, *, timeout: Optional[int | float] = 60, cooldown: timedelta = timedelta(seconds=2)):
        super().__init__(timeout=timeout)

        self.message = None
        self.last_message = None
        self.cooldown = cooldown

        self._event = None
        self._task = None

        self.allowed_mentions = AllowedMentions.all()

    def on_refresh(self) -> None | Awaitable[None]:
        """
        Called when the view is refreshed.
        """

        pass

    async def _sticky(self, channel: discord.TextChannel) -> None:
        assert self._event is not None

        # Initialize
        # Send the on_refresh callback
        if inspect.iscoroutinefunction(self.on_refresh):
            await self.on_refresh()
        else:
            self.on_refresh()

        # Send a new message
        self.message = await channel.send(view=self, allowed_mentions=self.allowed_mentions)

        while True:
            # Wait for events from the channel
            await self._event.wait()

            now = datetime.now()
            if self.last_message is not None:
                wait_until = self.last_message + self.cooldown

                if now < wait_until:
                    # Ratelimit deletion
                    delta = wait_until - now
                    await asyncio.sleep(delta.seconds)

            # Send the on_refresh callback
            if inspect.iscoroutinefunction(self.on_refresh):
                await self.on_refresh()
            else:
                self.on_refresh()

            self.last_message = datetime.now()

            # Delete the original message
            if self.message is not None:
                await self.message.delete()

            # Send a new message
            self.message = await channel.send(view=self, allowed_mentions=self.allowed_mentions)


class StickyServer:
    """
    Provides a generic way to create sticky messages.
    """

    channels: Dict[int, asyncio.Event]

    def __init__(self):
        self.channels = {}

    def stick(self, channel: discord.TextChannel, *, view: StickyView, allowed_mentions: AllowedMentions = AllowedMentions.all()) -> None:
        """
        Sends a view as a sticky message.
        """

        view.allowed_mentions = allowed_mentions

        view._event = self.get_event(channel)
        view._task = asyncio.create_task(view._sticky(channel))

    def get_event(self, channel: discord.TextChannel) -> asyncio.Event:
        id = channel.id
        if id not in self.channels:
            ev = asyncio.Event()
            self.channels[id] = ev
            return ev
        else:
            return self.channels[id]

    async def on_message(self, message: discord.Message) -> None:
        if not isinstance(message.channel, discord.TextChannel):
            return

        ev = self.get_event(message.channel)
        ev.set()
        ev.clear()


class StickyModule(Module):
    server: StickyServer

    def __init__(self):
        self.server = StickyServer()

    async def on_message(self, message: discord.Message) -> None:
        await self.server.on_message(message)
