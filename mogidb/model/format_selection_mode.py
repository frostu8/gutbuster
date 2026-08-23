from enum import IntEnum
from typing import Literal


class FormatSelectionMode(IntEnum):
    """
    Determines how a format will be selected.
    """

    VOTE = 0
    RANDOM = 1

    def __str__(self) -> str:
        match self.value:
            case self.RANDOM:
                return "Random"
            case self.VOTE:
                return "Vote"
            case _:
                raise ValueError("FormatSelectionMode with invalid value")

    # FUCK PYTHON!!!!
    def __bool__(self) -> Literal[True]:
        return True
