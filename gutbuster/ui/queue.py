from gutbuster.model.room import TeamMode
from sqlalchemy.ext.asyncio import AsyncEngine
from gutbuster.sticky import StickyView
import math
from datetime import datetime, timezone
from copy import copy
from gutbuster.config import Config
import asyncio
from asyncio import Task
from discord import ui, AllowedMentions, SeparatorSpacing
from typing import Optional, Dict, List
import discord
from gutbuster.servers import WatchedServer, ServerWatcher, GameSpeed
from gutbuster.model import Event, EventStatus, Participant


class QueueStatusContainer(ui.Container):
    config: Config
    event: Event
    server: Optional[WatchedServer]

    def __init__(self, config: Config, event: Event, *, server: Optional[WatchedServer] = None):
        super().__init__()
        self.config = config
        self.event = event
        self.server = server

    def color(self) -> discord.Color:
        """
        The accent color of the embed.
        """

        if self.server is None:
            return self.config.colors.server_offline

        if self.server.info is None:
            return self.config.colors.server_offline
        elif self.server.info.gametype_name == "Race":
            return self.config.colors.server_online_race
        elif self.server.info.gametype_name == "Battle":
            return self.config.colors.server_online_battle
        else:
            return self.config.colors.server_online_custom

    def _sort_teams(self) -> Dict[int, List[Participant]]:
        players = self.event.get_participants()

        # Sort players into teams
        teams: Dict[int, List[Participant]] = {}
        for player in players:
            # Skip subs
            if player.assigned_team is None:
                continue

            if player.assigned_team not in teams:
                teams[player.assigned_team] = [player]
            else:
                teams[player.assigned_team]

        return teams

    def regenerate(self) -> None:
        """
        Regenerates the embed.
        """

        self.clear_items()
        self.accent_color = self.color()

        if self.event.format is not None:
            content = f"Format __**{self.event.format.name}**__"
        else:
            content = ""

        # List participants
        if self.event.format and self.event.format.team_mode == TeamMode.FREE_FOR_ALL:
            # In free for all, each player is assigned their own team. This is
            # annoying, so default to the normal method of printing.
            for i, player in enumerate(self.event.get_participants()):
                # Skip subs
                if player.assigned_team is None:
                    continue

                mention = f"@{player.user.name}"
                if isinstance(player.user.user, discord.User | discord.Member):
                    mention = player.user.user.mention

                if i > 0:
                    # Add a space between mentions to make it more readable.
                    content += f" {mention}"
                else:
                    content += f"\n{mention}"
        else:
            teams = self._sort_teams()
            for team_index, team in teams.items():
                content += f"\n**Team {team_index+1}**"
                for player in team:
                    # Skip subs
                    if player.assigned_team is None:
                        continue

                    mention = f"@{player.user.name}"
                    if isinstance(player.user.user, discord.User | discord.Member):
                        mention = player.user.user.mention

                    content += f" {mention}"

        content += "\n\n"

        if self.server is None:
            # We're done, if there is no server information.
            self.add_item(ui.TextDisplay(content))
            return

        # Add the server label with the format selection.
        if self.server.label is not None:
            #content += f"⚡🔌 Playing on **{self.server.label}**\n"
            content += f"⚡ Playing on **{self.server.label}**\n"

        if self.server.info is None:
            content += "🔴 Server is offline."
        else:
            content += f"🟢 **IP** `{self.server.ip}:{self.server.port}`"

        self.add_item(ui.TextDisplay(content))

        if self.server.info is not None:
            # Build the server information listing
            self.add_item(ui.Separator(spacing=SeparatorSpacing.large))

            # Show map title
            content = f"**Map** {self.server.map_title}\n"

            if len(self.server.players) > 0:
                # List all players
                players = copy(self.server.players)
                players.sort(key=lambda a: a.score, reverse=True)
                for player in players:
                    score = str(player.score).rjust(4, " ")

                    if player.team == 255:
                        content += f"\n`{score}` *{player.name}*"
                    else:
                        content += f"\n`{score}` {player.name}"

            self.add_item(ui.TextDisplay(content))

        # Timestamp embed
        if self.server.last_updated is not None:
            epoch = datetime.fromtimestamp(0, timezone.utc)

            timestamp = math.trunc(
                (self.server.last_updated - epoch).total_seconds()
            )
            footer_content = f"Last updated at <t:{timestamp}:T>"

            self.add_item(ui.TextDisplay(footer_content))

    async def _wait_for_update(self) -> None:
        if self.server is None:
            raise ValueError("No server to update.")
        else:
            await self.server.update_event.wait()


class QueueStatus(StickyView):
    """
    A sticky message that reports the current status of a Mogi queue.
    """

    container: QueueStatusContainer

    db: AsyncEngine
    client: discord.Client
    _realtime_task: Optional[Task[None]]

    def __init__(self, client: discord.Client, db: AsyncEngine, config: Config, event: Event, servers: ServerWatcher, *, timeout: Optional[int | float] = 60*60):
        super().__init__(timeout=timeout)

        # Find server attached to event
        guild = discord.Object(id=event.room.discord_guild_id)
        try:
            server = next(filter(lambda s: s.remote == event.remote, servers.iter(guild)))
        except StopIteration:
            server = None

        self.container = QueueStatusContainer(config, event, server=server)
        self.add_item(self.container)

        self.db = db
        self.client = client
        self.message = None
        self._realtime_task = None

    @property
    def event(self) -> Event:
        return self.container.event

    @event.setter
    def set_event(self, event: Event) -> None:
        self.container.event = event
        self.container.regenerate()

    async def _realtime(self) -> None:
        while True:
            await self.container._wait_for_update()
            await self.update()

            if self.event.status == EventStatus.ENDED:
                self.stop()
                return

            # Update message
            if self.message is not None:
                await self.message.edit(view=self, allowed_mentions=AllowedMentions.none())

    @property
    def has_realtime(self) -> bool:
        return self.container.server is not None

    def realtime(self) -> None:
        """
        Creates a task that refreshes the server listing periodically.
        """

        if self._realtime_task is not None:
            self._realtime_task.cancel()
        self._realtime_task = asyncio.create_task(self._realtime())

    async def update(self) -> None:
        # Get new data for event
        async with self.db.connect() as conn:
            await self.event.refetch(conn)

        # Cache all users
        for participant in self.event.get_participants():
            await participant.user.fetch_user(self.client)

        # Regenerate
        self.container.regenerate()

    def stop(self) -> None:
        super().stop()
        if self._realtime_task is not None:
            self._realtime_task.cancel()

    async def on_refresh(self) -> None:
        await super().on_refresh()
        await self.update()

        if self.event.status == EventStatus.ENDED:
            self.stop()
            return

        if self.has_realtime:
            self.realtime()

    async def on_timeout(self) -> None:
        await super().on_timeout()
        if self._realtime_task is not None:
            self._realtime_task.cancel()
           
