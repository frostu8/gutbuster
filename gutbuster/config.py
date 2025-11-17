import tomllib
from typing import List, Dict, Any, Self
from dataclasses import dataclass
from discord import Color


def _get_str( map: Dict[str, Any], key: str, default: str) -> str:
    data = map.get(key, default)
    if not isinstance(data, str):
        raise ValueError(f"{key} is invalid type {type(data)}")

    return data


@dataclass
class Messages(object):
    gathered: List[str]

    @classmethod
    def fromdict(cls, data: Dict[str, Any]) -> Self:
        return cls(gathered=data.get("gathered", []))


@dataclass
class Colors(object):
    server_online: Color
    server_offline: Color

    @classmethod
    def fromdict(cls, data: Dict[str, Any]) -> Self:
        server_online = _get_str(data, "server_online", "#42ed53")
        server_offline = _get_str(data, "server_offline", "#d6240d")

        return cls(
            server_online=Color.from_str(server_online),
            server_offline=Color.from_str(server_offline),
        )


@dataclass
class Config(object):
    messages: Messages
    colors: Colors

    @classmethod
    def fromdict(cls, data: Dict[str, Any]) -> Self:
        messages = Messages.fromdict(data.get("messages", {}))
        colors = Colors.fromdict(data.get("color", {}))

        return cls(messages, colors)


def load(file_name: str) -> Config:
    file = open(file_name, "rb")
    config = tomllib.load(file)

    return Config.fromdict(config)
