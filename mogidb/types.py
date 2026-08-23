from typing import Literal


class Unset:
    """
    Used to represent values that are unset in responses.
    """

    def __bool__(self) -> Literal[False]:
        return False


UNSET: Unset = Unset()
