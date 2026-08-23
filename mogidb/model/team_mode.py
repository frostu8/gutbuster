from enum import IntEnum


class TeamMode(IntEnum):
    """
    Determines the team split of a format.
    """

    FFA = 1
    TWO_TEAMS = 2
    THREE_TEAMS = 3
    FOUR_TEAMS = 4
