"""
Room lifecycle socket events: create_room, join_room, leave_room.

Every handler follows the same shape: validate the payload with a Pydantic
schema (schemas/socket_events.py), delegate the actual state change to
services/room_manager.py, then emit the result. Handlers never touch Redis
directly - that keeps the room logic testable independent of Socket.IO and
means game_manager.py (Phase 3) can reuse the same room_manager functions.

`handle_departure` is exported and called from sockets/connection.py's
`disconnect` handler too, since an abrupt disconnect and an explicit
`leave_room` need identical cleanup.
"""
import logging

from pydantic import ValidationError

from schemas.socket_events import CreateRoomPayload, JoinRoomPayload
from services import room_manager
from sockets.server import sio

logger = logging.getLogger("npat.socket.rooms")


def _validation_error_message(exc: ValidationError) -> str:
    """Pydantic's default error dump is verbose - collapse it to one line
    per field, good enough for a client-side toast/error banner."""
    parts = [f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()]
    return "; ".join(parts)


@sio.on("create_room")
async def handle_create_room(sid, data):
    try:
        payload = CreateRoomPayload(**(data or {}))
    except ValidationError as e:
        await sio.emit("error", {"event": "create_room", "message": _validation_error_message(e)}, to=sid)
        return

    room_code = await room_manager.create_room(
        sid, payload.player_id, payload.username, payload.avatar_config.model_dump()
    )
    sio.enter_room(sid, room_code)

    state = await room_manager.get_room_state(room_code)
    await sio.emit("room_created", state, to=sid)
    logger.info("Room %s created by %s", room_code, payload.player_id)


@sio.on("join_room")
async def handle_join_room(sid, data):
    try:
        payload = JoinRoomPayload(**(data or {}))
    except ValidationError as e:
        await sio.emit("error", {"event": "join_room", "message": _validation_error_message(e)}, to=sid)
        return

    room_code = payload.room_code.strip().upper()

    try:
        await room_manager.join_room(
            sid, room_code, payload.player_id, payload.username, payload.avatar_config.model_dump()
        )
    except room_manager.RoomNotFound:
        await sio.emit("error", {"event": "join_room", "message": f"Room {room_code} not found"}, to=sid)
        return
    except room_manager.RoomFull:
        await sio.emit("error", {"event": "join_room", "message": f"Room {room_code} is full"}, to=sid)
        return
    except room_manager.RoomAlreadyStarted:
        await sio.emit(
            "error", {"event": "join_room", "message": f"Room {room_code} has already started"}, to=sid
        )
        return

    sio.enter_room(sid, room_code)

    # Broadcast to the whole room (including the joiner) - this single
    # event both confirms the join to the new player and updates
    # everyone else's player list, matching the spec's event list rather
    # than adding a separate "room_joined" event just for the joiner.
    state = await room_manager.get_room_state(room_code)
    await sio.emit("player_joined", state, room=room_code)
    logger.info("Player %s joined room %s", payload.player_id, room_code)


@sio.on("leave_room")
async def handle_leave_room(sid, data):
    await handle_departure(sid)


async def handle_departure(sid: str) -> None:
    """Shared cleanup for both an explicit `leave_room` event and an
    abrupt disconnect - see sockets/connection.py."""
    result = await room_manager.leave_room_by_sid(sid)
    if result is None:
        return

    room_code = result["room_code"]
    sio.leave_room(sid, room_code)

    if result["room_deleted"]:
        logger.info("Room %s deleted (last player left)", room_code)
        return

    state = await room_manager.get_room_state(room_code)
    await sio.emit(
        "player_left",
        {"player_id": result["player_id"], "new_host_id": result["new_host_id"], **state},
        room=room_code,
    )
    logger.info("Player %s left room %s", result["player_id"], room_code)
