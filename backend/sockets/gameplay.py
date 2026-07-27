"""
Gameplay socket events: start_game, submit_answers, player_done, and
next_round.

`next_round` is an addition beyond the original event list: the spec
describes rounds advancing automatically after an end-of-round stats
screen, but that screen (and the achievement engine driving it) doesn't
exist until Phase 5. For now the host explicitly advances the round -
worth revisiting once the automatic end-of-round flow lands.
"""
import logging

from pydantic import ValidationError

from schemas.round import PlayerDoneRequest, SubmitAnswersRequest
from services import game_manager, room_manager
from sockets.server import sio

logger = logging.getLogger("npat.socket.gameplay")


def _validation_error_message(exc: ValidationError) -> str:
    parts = [f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()]
    return "; ".join(parts)


@sio.on("start_game")
async def handle_start_game(sid, data):
    room_code = (data or {}).get("room_code")
    player_id = (data or {}).get("player_id")
    if not room_code or not player_id:
        await sio.emit(
            "error", {"event": "start_game", "message": "room_code and player_id are required"}, to=sid
        )
        return

    try:
        result = await game_manager.start_game(room_code, player_id)
    except room_manager.RoomNotFound:
        await sio.emit("error", {"event": "start_game", "message": f"Room {room_code} not found"}, to=sid)
        return
    except game_manager.NotHost:
        await sio.emit("error", {"event": "start_game", "message": "Only the host can start the game"}, to=sid)
        return
    except game_manager.NotEnoughPlayers:
        await sio.emit(
            "error", {"event": "start_game", "message": "Not enough players to start"}, to=sid
        )
        return
    except game_manager.GameAlreadyStarted:
        await sio.emit(
            "error", {"event": "start_game", "message": "Game has already started"}, to=sid
        )
        return

    await sio.emit("game_started", {"room_code": room_code}, room=room_code)
    await sio.emit("new_round", result, room=room_code)
    logger.info("Game started in room %s", room_code)


@sio.on("submit_answers")
async def handle_submit_answers(sid, data):
    try:
        payload = SubmitAnswersRequest(**(data or {}))
    except ValidationError as e:
        await sio.emit(
            "error", {"event": "submit_answers", "message": _validation_error_message(e)}, to=sid
        )
        return

    try:
        await game_manager.submit_answers(
            payload.room_code, payload.player_id, [a.model_dump() for a in payload.answers]
        )
    except game_manager.GameNotInProgress:
        await sio.emit(
            "error", {"event": "submit_answers", "message": "Game is not in progress"}, to=sid
        )
        return
    except game_manager.RoundAlreadyLocked:
        await sio.emit(
            "error", {"event": "submit_answers", "message": "Round is already locked"}, to=sid
        )
        return
    # No broadcast here - other players don't see draft answers, only the
    # eventual locked reveal via round_locked below.


@sio.on("player_done")
async def handle_player_done(sid, data):
    try:
        payload = PlayerDoneRequest(**(data or {}))
    except ValidationError as e:
        await sio.emit(
            "error", {"event": "player_done", "message": _validation_error_message(e)}, to=sid
        )
        return

    try:
        result = await game_manager.player_done(
            payload.room_code,
            payload.player_id,
            [a.model_dump() for a in payload.answers] if payload.answers else None,
        )
    except game_manager.GameNotInProgress:
        await sio.emit(
            "error", {"event": "player_done", "message": "Game is not in progress"}, to=sid
        )
        return
    except game_manager.RoundAlreadyLocked:
        # Someone else's Done already locked the round a moment earlier -
        # not an error from this player's point of view (they didn't do
        # anything wrong), so no `error` event; they'll get the same
        # round_locked broadcast as everyone else.
        return

    await sio.emit("round_locked", result, room=payload.room_code)
    logger.info(
        "Round %s locked in room %s by %s", result["round_number"], payload.room_code, payload.player_id
    )


@sio.on("next_round")
async def handle_next_round(sid, data):
    room_code = (data or {}).get("room_code")
    player_id = (data or {}).get("player_id")
    if not room_code or not player_id:
        await sio.emit(
            "error", {"event": "next_round", "message": "room_code and player_id are required"}, to=sid
        )
        return

    if not await room_manager.is_host(room_code, player_id):
        await sio.emit(
            "error", {"event": "next_round", "message": "Only the host can advance the round"}, to=sid
        )
        return

    try:
        result = await game_manager.start_next_round(room_code)
    except game_manager.GameNotInProgress:
        await sio.emit(
            "error", {"event": "next_round", "message": "Game is not in progress"}, to=sid
        )
        return

    if result["finished"]:
        await sio.emit("game_finished", {"room_code": room_code}, room=room_code)
        logger.info("Game finished in room %s", room_code)
    else:
        await sio.emit("new_round", result, room=room_code)
