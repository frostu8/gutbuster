import tomllib
from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class Messages(object):
    gathered: List[str]

    @classmethod
    def fromdict(cls, data: Dict[str, Any]):
        return cls(gathered=data.get('gathered', []))


@dataclass
class Config(object):
    messages: Messages

    @classmethod
    def fromdict(cls, data: Dict[str, Any]):
        messages = Messages.fromdict(data.get('messages', {}))

        return cls(messages)


def load(file_name: str) -> Config:
    file = open(file_name, "rb")
    config = tomllib.load(file)

    return Config.fromdict(config)
