from enum import IntFlag


class ServerFlags(IntFlag):
    LOTS_OF_ADDONS = 0x20
    DEDICATED = 0x40
    VOICE_ENABLED = 0x80
