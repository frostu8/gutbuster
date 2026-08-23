from asyncio import EventLoop
from typing import Any

import httpx

from .dacite import FromDict
from .model import ApiError as ErrorData
from .model import EventFormat, Guild, Room, RoomOptions, TeamMode


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
    loop: EventLoop

    _base_url: str

    def __init__(
        self,
        base_url: str,
        access_token: str,
    ):
        self._base_url = base_url

        self.loop = EventLoop()
        self.client = httpx.AsyncClient(
            headers={
                "X-API-KEY": access_token,
            }
        )

    def __del__(self):
        """
        Closes the client when all references are lost.
        """

        self.loop.run_until_complete(self.client.aclose())
        self.loop.close()


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
        options: RoomOptions | None = None
    ) -> Room:
        if options is None:
            options = RoomOptions()

        content = options.to_dict()
        content["room_id"] = channel_id
        content["name"] = channel_name

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
        channel_name: str,
        options: RoomOptions | None = None
    ) -> Room:
        if options is None:
            options = RoomOptions()

        content = options.to_dict()
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
            content["team_mode"] = team_mode
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
            content["team_mode"] = team_mode

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
