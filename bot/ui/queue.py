import asyncio
import math
from asyncio import Task
from copy import copy
from datetime import UTC, datetime

import discord
from discord import AllowedMentions, SeparatorSpacing, ui

import mogidb
from bot.config import Config
from mogidb.model import Event, EventParticipant, EventStatus, GameServer, TeamMode


class QueueStatusContainer(ui.Container):
    config: Config
    client: discord.Client
    event: Event

    def __init__(self, config: Config, client: discord.Client, event: Event):
        super().__init__()
        self.config = config
        self.client = client
        self.event = event

    @property
    def server(self) -> GameServer | None:
        return self.event.server

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

    def _sort_teams(self) -> dict[int, list[EventParticipant]]:
        # Sort players into teams
        teams: dict[int, list[EventParticipant]] = {}
        for player in self.event.players:
            # Skip subs
            if player.team_number is None:
                continue

            if player.team_number not in teams:
                teams[player.team_number] = [player]
            else:
                teams[player.team_number].append(player)

        return teams

    async def update(self) -> None:
        """
        Regenerates the embed.
        """

        self.clear_items()
        self.accent_color = self.color()

        content = f"Code `{self.event.id}`\n"

        if self.event.format is not None:
            content += f"Format __**{self.event.format.name}**__"

        # List participants
        if self.event.format and self.event.format.team_mode == TeamMode.FFA:
            # In free for all, each player is assigned their own team. This is
            # annoying, so default to the normal method of printing.
            for i, player in enumerate(self.event.players):
                # Skip subs
                if player.team_number is None:
                    continue

                mention = f"{player.user.display_name}"
                if player.user.discord_user_id is not None:
                    discord_user = self.client.get_user(player.user.discord_user_id)
                    if discord_user is None:
                        discord_user = await self.client.fetch_user(player.user.discord_user_id)

                    mention = discord_user.mention

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
                    if player.team_number is None:
                        continue

                    mention = f"{player.user.display_name}"
                    if player.user.discord_user_id is not None:
                        discord_user = self.client.get_user(player.user.discord_user_id)
                        if discord_user is None:
                            discord_user = await self.client.fetch_user(player.user.discord_user_id)

                        mention = discord_user.mention

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
            content += f"🟢 **IP** `{self.server.remote}`"

        self.add_item(ui.TextDisplay(content))

        if self.server.info is not None:
            # Build the server information listing
            self.add_item(ui.Separator(spacing=SeparatorSpacing.large))

            # Show map title
            content = f"**Map** {self.server.info.map_name}\n"

            if len(self.server.info.players) > 0:
                # List all players
                players = copy(self.server.info.players)
                players.sort(key=lambda a: a.score, reverse=True)
                for player in players:
                    score = str(player.score).rjust(4, " ")

                    if player.team == 255:
                        content += f"\n`{score}` *{player.name}*"
                    else:
                        content += f"\n`{score}` {player.name}"

            self.add_item(ui.TextDisplay(content))

        # Timestamp embed
        if self.server.last_update_time is not None:
            epoch = datetime.fromtimestamp(0, UTC)

            timestamp = math.trunc(
                (self.server.last_update_time - epoch).total_seconds()
            )
            footer_content = f"Last updated at <t:{timestamp}:T>"

            self.add_item(ui.TextDisplay(footer_content))


class QueueStatus(ui.LayoutView):
    """
    A message that reports the current status of a Mogi queue.
    """

    db: mogidb.Client
    client: discord.Client

    event: Event

    _realtime_task: Task[None] | None

    def __init__(self, config: Config, client: discord.Client, db: mogidb.Client, event: Event, *, timeout: float | None = 3000):
        super().__init__(timeout=timeout)

        self.event = event

        self.db = db
        self.config = config
        self.client = client
        self.message = None
        self._realtime_task = None

    async def update(self):
        assert self.event.room
        assert self.event.room.guild

        room = self.event.room
        guild = self.event.room.guild

        # Update the event on the view
        event = await self.db.get_event(guild.id, room.id, self.event.id)
        if event is None:
            # Event was removed?
            return

        self.event = event

        # If needed, fetch user data into cache
        for player in self.event.players:
            if player.user.discord_user_id is None:
                continue

            user = self.client.get_user(player.user.discord_user_id)
            if user is None:
                await self.client.fetch_user(player.user.discord_user_id)

        # Refresh items
        self.clear_items()

        container = QueueStatusContainer(self.config, self.client, self.event)
        await container.update()

        self.add_item(container)

    async def _realtime(self) -> None:
        while True:
            # Update on cycle
            await asyncio.sleep(30)
            await self.update()

            if self.event.status == EventStatus.CONCLUDED:
                self.stop()
                return

            # Update message
            if self.message is not None:
                await self.message.edit(view=self, allowed_mentions=AllowedMentions.none())

    @property
    def has_realtime(self) -> bool:
        return self.event.server is not None

    def realtime(self) -> None:
        """
        Creates a task that refreshes the server listing periodically.
        """

        if self._realtime_task is not None:
            self._realtime_task.cancel()
        self._realtime_task = asyncio.create_task(self._realtime())

    def stop(self) -> None:
        super().stop()
        if self._realtime_task is not None:
            self._realtime_task.cancel()

    async def on_timeout(self) -> None:
        await super().on_timeout()
        if self._realtime_task is not None:
            self._realtime_task.cancel()
           
