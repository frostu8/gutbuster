import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Self

import dacite
from discord import Color


@dataclass
class Messages:
    gathered: list[str]

    @classmethod
    def from_dict(cls, src: Mapping[str, Any]) -> Self:
        return dacite.from_dict(cls, src)


@dataclass
class Colors:
    server_online_race: Color = field(default_factory=lambda: Color.from_str("#42ed53"))
    server_online_battle: Color = field(default_factory=lambda: Color.from_str("#42ed53"))
    server_online_custom: Color = field(default_factory=lambda: Color.from_str("#42ed53"))
    server_offline: Color = field(default_factory=lambda: Color.from_str("#d6240d"))

    @classmethod
    def from_dict(cls, src: Mapping[str, Any]) -> Self:
        return dacite.from_dict(cls, src)


@dataclass
class Config:
    messages: Messages
    colors: Colors = field(default_factory=lambda: Colors())
    api_endpoint: str = "http://localhost:8000"

    @classmethod
    def from_dict(cls, src: Mapping[str, Any]) -> Self:
        return dacite.from_dict(cls, src)


def load(file_name: str) -> Config:
    with open(file_name, "rb") as file:
        config = tomllib.load(file)

    return Config.from_dict(config)
