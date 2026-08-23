from asyncio import EventLoop
from typing import Any

import httpx

from .dacite import FromDict
from .model import ApiError as ErrorData, EventStatus
from .model import (
    Event,
    EventFormat,
    EventParticipant,
    GameServer,
    Guild,
    JoinEventResponse,
    Room,
    RoomOptions,
    TeamMode,
    User,
)


class ApiError(Exception):
    """
    The request went through, but an error happened on the API.
    """

    _status_code: int
    _error: ErrorData

    def __init__(self, status_code: int, error: ErrorData):
        super().__init__(error.message)
        self._status_code = status_code
        self._error = error

    @property
    def status_code(self) -> int:
        return self._status_code

    @property
    def message(self) -> str:
        return self._error.message

    def is_not_found(self) -> bool:
        return self._status_code == 404


class Client:
    """
    MogiDB API client.
    """

    client: httpx.AsyncClient

    _base_url: str

    def __init__(
        self,
        base_url: str,
        access_token: str,
    ):
        self._base_url = base_url

        # Instantiate client
        self.client = httpx.AsyncClient(
            headers={
                "X-API-KEY": access_token,
            }
        )

    async def aclose(self) -> None:
        """
        Closes the underlying client.
        """

        await self.client.aclose()

    async def _req_raw(self, req: httpx.Request) -> Any:
        res = await self.client.send(req)

        if res.is_success:
            if res.status_code == 204:
                # Skip no content responses
                return None
            else:
                # Try to decode result
                return res.json()
        else:
            # Decode API error
            api_error = ErrorData.from_dict(res.json())
            raise ApiError(res.status_code, api_error)

    async def _req[T: FromDict](self, req: httpx.Request, ty: type[T]) -> T:
        res = await self.client.send(req)

        if res.is_success:
            # Try to decode result
            return ty.from_dict(res.json())
        else:
            # Decode API error
            api_error = ErrorData.from_dict(res.json())
            raise ApiError(res.status_code, api_error)

    async def _req_many[T: FromDict](self, req: httpx.Request, ty: type[T]) -> list[T]:
        res = await self.client.send(req)

        if res.is_success:
            # Try to decode result
            json = res.json()
            assert isinstance(json, list)
            return [ty.from_dict(inner) for inner in json]
        else:
            # Decode API error
            api_error = ErrorData.from_dict(res.json())
            raise ApiError(res.status_code, api_error)

    async def _req_optional[T: FromDict](self, req: httpx.Request, ty: type[T]) -> T | None:
        try:
            return await self._req(req, ty)
        except ApiError as err:
            if err.is_not_found():
                return None
            else:
                raise

    async def create_guild(self, guild_id: int, options: RoomOptions | None = None) -> Guild:
        if options is None:
            options = RoomOptions()

        content = options.to_dict()
        content["guild_id"] = guild_id
        req = self.client.build_request("POST", f"{self._base_url}/guilds", json=content)
        return await self._req(req, Guild)

    async def get_guild(self, guild_id: int) -> Guild | None:
        req = self.client.build_request("GET", f"{self._base_url}/guilds/{guild_id}")
        return await self._req_optional(req, Guild)

    async def update_guild(self, guild_id: int, options: RoomOptions | None = None) -> Guild:
        if options is None:
            options = RoomOptions()

        content = options.to_dict()
        content["guild_id"] = guild_id
        req = self.client.build_request("PATCH", f"{self._base_url}/guilds/{guild_id}", json=content)
        return await self._req(req, Guild)

    async def create_room(
        self,
        guild_id: int,
        channel_id: int,
        channel_name: str,
        enabled: bool | None = None,
        options: RoomOptions | None = None
    ) -> Room:
        if options is None:
            options = RoomOptions()

        content = options.to_dict()
        content["room_id"] = channel_id
        content["name"] = channel_name

        if enabled is not None:
            content["enabled"] = enabled

        req = self.client.build_request("POST", f"{self._base_url}/guilds/{guild_id}/rooms", json=content)
        return await self._req(req, Room)

    async def get_room(
        self,
        guild_id: int,
        channel_id: int,
    ) -> Room | None:
        req = self.client.build_request("GET", f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}")
        return await self._req_optional(req, Room)

    async def update_room(
        self,
        guild_id: int,
        channel_id: int,
        channel_name: str | None = None,
        enabled: bool | None = None,
        options: RoomOptions | None = None
    ) -> Room:
        if options is None:
            options = RoomOptions()

        content = options.to_dict()
        if enabled is not None:
            content["enabled"] = enabled
        if channel_name is not None:
            content["name"] = channel_name

        req = self.client.build_request("PATCH", f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}", json=content)
        return await self._req(req, Room)

    async def delete_room(
        self,
        guild_id: int,
        channel_id: int,
    ) -> None:
        req = self.client.build_request("DELETE", f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}")
        await self._req_raw(req)

    async def list_event_formats(
        self,
        guild_id: int,
        channel_id: int,
    ) -> list[EventFormat]:
        req = self.client.build_request("GET", f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}/formats")
        return await self._req_many(req, EventFormat)

    async def create_event_format(
        self,
        guild_id: int,
        channel_id: int,
        name: str,
        team_mode: TeamMode | None = None,
        servers: list[int] | None = None,
    ) -> EventFormat:
        content: dict[str, Any] = {"name": name}
        if team_mode is not None:
            content["team_mode"] = team_mode.value
        if servers is not None:
            content["servers"] = servers

        req = self.client.build_request("POST", f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}/formats", json=content)
        return await self._req(req, EventFormat)

    async def get_event_format(
        self,
        guild_id: int,
        channel_id: int,
        format_id: int,
    ) -> EventFormat | None:
        req = self.client.build_request("GET", f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}/formats/{format_id}")
        return await self._req_optional(req, EventFormat)

    async def update_event_format(
        self,
        guild_id: int,
        channel_id: int,
        format_id: int,
        name: str | None = None,
        team_mode: TeamMode | None = None,
        servers: list[int] | None = None,
    ) -> EventFormat:
        content: dict[str, Any] = {}
        if name is not None:
            content["name"] = name
        if servers is not None:
            content["servers"] = servers
        if team_mode is not None:
            content["team_mode"] = team_mode.value

        req = self.client.build_request("PATCH", f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}/formats/{format_id}", json=content)
        return await self._req(req, EventFormat)

    async def delete_event_format(
        self,
        guild_id: int,
        channel_id: int,
        format_id: int,
    ) -> None:
        req = self.client.build_request("DELETE", f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}/formats/{format_id}")
        return await self._req_raw(req)

    async def list_events(
        self,
        guild_id: int,
        active: bool | None = None,
        user_id: str | None = None,
    ) -> list[Event]:
        params: dict[str, Any] = {}
        if active is not None:
            params["active"] = active
        if user_id is not None:
            params["user"] = user_id

        req = self.client.build_request("GET", f"{self._base_url}/guilds/{guild_id}/events", params=params)
        return await self._req_many(req, Event)

    async def create_event(
        self,
        guild_id: int,
        channel_id: int,
        title: str | None = None,
    ) -> Event:
        content: dict[str, Any] = {}
        if title is not None:
            content["title"] = title

        req = self.client.build_request("POST", f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}/events", json=content)
        return await self._req(req, Event)

    async def get_event(
        self,
        guild_id: int,
        channel_id: int,
        event_id: str,
    ) -> Event | None:
        req = self.client.build_request("GET", f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}/events/{event_id}")
        return await self._req_optional(req, Event)

    async def update_event(
        self,
        guild_id: int,
        channel_id: int,
        event_id: str,
        title: str | None = None,
        status: EventStatus | None = None,
        format: int | None = None,
        server: int | None = None,
    ) -> Event:
        content: dict[str, Any] = {}
        if title is not None:
            content["title"] = title
        if status is not None:
            content["status"] = status.value
        if format is not None:
            content["format"] = format
        if server is not None:
            content["server"] = server

        req = self.client.build_request("PATCH", f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}/events/{event_id}", json=content)
        return await self._req(req, Event)

    async def delete_event(
        self,
        guild_id: int,
        channel_id: int,
        event_id: str,
    ) -> None:
        req = self.client.build_request("DELETE", f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}/events/{event_id}")
        return await self._req_raw(req)

    async def get_current_event(
        self,
        guild_id: int,
        channel_id: int,
    ) -> Event | None:
        req = self.client.build_request("GET", f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}/events/~current")
        return await self._req_optional(req, Event)

    async def list_event_participants(
        self,
        guild_id: int,
        channel_id: int,
        event_id: str,
    ) -> list[EventParticipant]:
        req = self.client.build_request("GET", f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}/events/{event_id}/participants")
        return await self._req_many(req, EventParticipant)

    async def join_event(
        self,
        guild_id: int,
        channel_id: int,
        event_id: str,
        user_id: str,
    ) -> JoinEventResponse:
        req = self.client.build_request(
            "POST",
            f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}/events/{event_id}/participants",
            json={"user_id": user_id},
        )
        return await self._req(req, JoinEventResponse)

    async def assign_teams(
        self,
        guild_id: int,
        channel_id: int,
        event_id: str,
        balance_mode: str | None = None,
        players: list[str] | None = None,
    ) -> Event:
        content: dict[str, Any] = {}
        if balance_mode is not None:
            content["balance_mode"] = balance_mode
        if players is not None:
            content["players"] = players

        req = self.client.build_request(
            "POST",
            f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}/events/{event_id}/participants/teams~assign",
            json=content,
        )
        return await self._req(req, Event)

    async def leave_event(
        self,
        guild_id: int,
        channel_id: int,
        event_id: str,
        user_id: str,
    ) -> Event:
        req = self.client.build_request(
            "DELETE",
            f"{self._base_url}/guilds/{guild_id}/rooms/{channel_id}/events/{event_id}/participants/{user_id}",
        )
        return await self._req(req, Event)

    async def create_server(
        self,
        guild_id: int,
        remote: str,
        label: str | None = None,
        note: str | None = None,
    ) -> GameServer:
        content: dict[str, Any] = {"remote": remote}
        if label is not None:
            content["label"] = label
        if note is not None:
            content["note"] = note

        req = self.client.build_request("POST", f"{self._base_url}/guilds/{guild_id}/servers", json=content)
        return await self._req(req, GameServer)

    async def list_servers(
        self,
        guild_id: int,
    ) -> list[GameServer]:
        req = self.client.build_request("GET", f"{self._base_url}/guilds/{guild_id}/servers")
        return await self._req_many(req, GameServer)

    async def get_server(
        self,
        guild_id: int,
        server_id: int,
    ) -> GameServer | None:
        req = self.client.build_request("GET", f"{self._base_url}/guilds/{guild_id}/servers/{server_id}")
        return await self._req_optional(req, GameServer)

    async def update_server(
        self,
        guild_id: int,
        server_id: int,
        label: str | None = None,
        note: str | None = None,
    ) -> GameServer:
        content: dict[str, Any] = {}
        if label is not None:
            content["label"] = label
        if note is not None:
            content["note"] = note

        req = self.client.build_request("PATCH", f"{self._base_url}/guilds/{guild_id}/servers/{server_id}", json=content)
        return await self._req(req, GameServer)

    async def delete_server(
        self,
        guild_id: int,
        server_id: int,
    ) -> None:
        req = self.client.build_request("DELETE", f"{self._base_url}/guilds/{guild_id}/servers/{server_id}")
        await self._req_raw(req)

    async def upsert_user(
        self,
        discord_user_id: int,
        display_name: str,
    ) -> User:
        req = self.client.build_request(
            "PUT",
            f"{self._base_url}/users/{discord_user_id}",
            json={"display_name": display_name},
        )
        return await self._req(req, User)

    async def get_user(
        self,
        user_id: str,
    ) -> User | None:
        req = self.client.build_request("GET", f"{self._base_url}/users/{user_id}")
        return await self._req_optional(req, User)
