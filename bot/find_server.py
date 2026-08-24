import logging

import mogidb
from mogidb import Unset
from mogidb.model import Event, EventFormat, EventStatus, GameServer

logger = logging.getLogger(__name__)


async def find_server(event: Event, *, format: EventFormat | None = None, db: mogidb.Client) -> GameServer | None:
    """
    Finds an available server for a mogi.
    """

    assert event.room
    assert event.room.guild

    room = event.room
    guild = event.room.guild

    selected_format = event.format
    if format is not None:
        selected_format = format

    if selected_format is None:
        raise ValueError("Format must be selected to find a server")

    # Find server for queue
    if isinstance(selected_format.servers, Unset):
        # "Silently" fetch the format
        logger.info(f"Fetching format {selected_format.name} from server...")
        selected_format = await db.get_event_format(guild.id, room.id, selected_format.id) or selected_format

    assert not isinstance(selected_format.servers, Unset)

    # Filter servers being used in active mogis
    active_events = await db.list_events(guild.id, active=True)

    used_servers = (event.server for event in active_events if event.status != EventStatus.LFG)
    used_servers = {server.id for server in used_servers if server is not None}

    servers = [server for server in selected_format.servers if server.id not in used_servers]
    if len(servers) > 0:
        return servers.pop()
    else:
        return None

