"""
Baseline connect/disconnect logging.

Room join/leave, game start, answer submission etc. are NOT handled here -
those land in Phase 2 (sockets/rooms.py) and Phase 3 (sockets/gameplay.py) as
server-authoritative event handlers on top of services/room_manager.py and
services/game_manager.py.
"""
import logging

from sockets.server import sio

logger = logging.getLogger("npat.socket")


@sio.event
async def connect(sid, environ, auth):
    logger.info("Client connected: %s", sid)


@sio.event
async def disconnect(sid):
    logger.info("Client disconnected: %s", sid)
    # Phase 2 TODO: look up which room/player this sid belonged to
    # (via a sid -> player_id mapping in Redis) and emit `player_left`
    # to the rest of that room.
