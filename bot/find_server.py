import logging

import mogidb
from mogidb import Unset
from mogidb.model import Event, EventStatus, GameServer

logger = logging.getLogger(__name__)


async def find_server(event: Event, *, db: mogidb.Client) -> GameServer | None:
    """
    Finds an available server for a mogi.
    """

    assert event.room
    assert event.room.guild

    room = event.room
    guild = event.room.guild

    if event.format is None:
        raise ValueError("Format must be selected to find a server")

    # Find server for queue
    if isinstance(event.format.servers, Unset):
        # "Silently" fetch the format
        logger.info(f"Fetching format {event.format.name} from server...")
        event.format = await db.get_event_format(guild.id, room.id, event.format.id) or event.format

    assert not isinstance(event.format.servers, Unset)

    # Filter servers being used in active mogis
    active_events = await db.list_events(guild.id, active=True)

    used_servers = (event.server for event in active_events if event.status != EventStatus.LFG)
    used_servers = {server.id for server in used_servers if server is not None}

    servers = [server for server in event.format.servers if server.id not in used_servers]
    if len(servers) > 0:
        return servers.pop()
    else:
        return None

