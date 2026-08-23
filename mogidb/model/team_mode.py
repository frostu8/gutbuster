from enum import IntEnum


class TeamMode(IntEnum):
    """
    Determines the team split of a format.
    """

    FFA = 1
    TWO_TEAMS = 2
    THREE_TEAMS = 3
    FOUR_TEAMS = 4

    def __str__(self) -> str:
        match self.value:
            case self.FFA:
                return "Free-for-all"
            case self.TWO_TEAMS:
                return "Two teams"
            case self.THREE_TEAMS:
                return "Three teams"
            case self.FOUR_TEAMS:
                return "Four teams"
            case _:
                raise ValueError("Invalid value for TeamMode")
