import random
import re
from typing import Protocol

import discord


class Formatter:
    """
    A formatter.
    """

    users: list[discord.User]

    def __init__(self, *, users: list[discord.User]):
        self.users = users

    def random_player(self) -> str | None:
        """
        Gets the name of a random player.
        """

        if len(self.users) > 0:
            return random.choice(self.users).display_name
        else:
            return None


class Part(Protocol):
    """
    A single part of a format string.
    """

    def format(self, f: Formatter) -> str:
        ...


class LiteralPart(Part):
    """
    A part that is just literal text.
    """

    text: str

    def __init__(self, text: str):
        self.text = text

    def format(self, f: Formatter) -> str:
        del f
        return self.text


class RandomUser(Part):
    """
    Produces the name of a random user.
    """

    def __init__(self):
        pass

    def format(self, f: Formatter) -> str:
        return f.random_player() or ''


class RandomDice(Part):
    """
    Produces a random dice roll.
    """

    count: int
    sides: int

    def __init__(self, sides: int, count: int = 1):
        if sides < 1:
            raise ValueError(f"invalid sides count {sides}")

        self.sides = sides
        self.count = count

    def format(self, f: Formatter) -> str:
        del f
        result = sum(random.randrange(1, self.sides) for _ in range(self.count))
        return str(result)


class FormatString:
    """
    A compiled format string.
    """

    _parts: list[Part]

    def __init__(self):
        self._parts = []

    def append(self, part: Part):
        self._parts.append(part)

    def format(self, f: Formatter) -> str:
        return ''.join(part.format(f) for part in self._parts)

def parse_random_part(input: str) -> tuple[Part, str]:
    """
    Parses a single part of the form %r<d>
    """

    assert len(input) > 0

    switch = input[0]
    match switch:
        case 'u':
            return RandomUser(), input[1:]
        case _ if switch.isdigit() or switch == 'd':
            # Use dice side no
            match = re.search(r'(\d*)d(\d+)', input)

            if match:
                # Get dice count (if it exists)
                count_str = match[1]
                if len(count_str) > 0:
                    count = int(count_str)
                else:
                    count = 1

                # Get dice sides
                sides = int(match[2])

                return RandomDice(sides, count), input[match.end():]
            else:
                raise ValueError(f'invalid random digit syntax: {input}')
        case _:
            raise ValueError(f'unexpected switch: %{switch}')

def parse_part(input: str) -> tuple[Part, str]:
    """
    Parses a single part.
    """

    assert len(input) > 0

    switch = input[0]
    match switch:
        case 'r':
            # Get control char
            return parse_random_part(input[1:])
        case '%':
            # Produce literal paren
            return LiteralPart('%'), input[2:]
        case _:
            raise ValueError(f'unexpected switch: %{switch}')

def parse(input: str) -> FormatString:
    """
    Parses a format string.
    """

    output = FormatString()
    while len(input) > 0:
        start_idx = input.find('%')
        if start_idx >= 0:
            output.append(LiteralPart(input[:start_idx]))

            # Parse part
            part, rest = parse_part(input[start_idx+1:])
            output.append(part)

            # Continue with rest
            input = rest
        else:
            output.append(LiteralPart(input))
            break

    return output

__all__ = [
    'FormatString',
    'Formatter',
    'LiteralPart',
    'Part',
    'RandomDice',
    'RandomUser',
    'parse'
]
