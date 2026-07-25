"""
Connection lifecycle: connect logging, and disconnect cleanup delegated to
sockets/rooms.py so an abrupt disconnect gets exactly the same room
cleanup (player removal, host reassignment, `player_left` broadcast) as an
explicit `leave_room` event.
"""
import logging

from sockets.server import sio
from sockets.rooms import handle_departure

logger = logging.getLogger("npat.socket")


@sio.event
async def connect(sid, environ, auth):
    logger.info("Client connected: %s", sid)


@sio.event
async def disconnect(sid):
    logger.info("Client disconnected: %s", sid)
    await handle_departure(sid)
