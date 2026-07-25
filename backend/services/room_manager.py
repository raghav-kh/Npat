"""
Server-authoritative room state, backed by Redis.

Deliberately NOT touching Postgres here: a room's live membership changes
constantly (joins, leaves, reconnects) and doesn't need to survive a
process restart the way completed rounds/results do. Postgres involvement
starts in Phase 3 (writing completed rounds) and at game-finish (writing
RoomResult). See database/session.py vs database/redis_client.py for the
same split explained from the connection-setup side.

Redis key layout:
    room:{code}            hash  - room-level fields (status, host, created_at)
    room:{code}:players    hash  - player_id -> JSON-encoded player state
    sid:{socket_id}        string - JSON {player_id, room_code}, used to
                                     resolve an abrupt disconnect back to
                                     "which player, in which room"

All three share a TTL so an abandoned room (everyone disconnects without
an explicit leave) eventually cleans itself out of Redis rather than
accumulating forever.
"""
import json
import random
from datetime import datetime, timezone

from config import settings
from database.redis_client import get_redis

ROOM_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no O/0, I/1 - avoids ambiguous codes read aloud
ROOM_TTL_SECONDS = 6 * 60 * 60  # 6 hours - generous enough for a long play session, bounded enough to self-clean


class RoomError(Exception):
    """Base class for room errors the socket layer translates into an `error` event."""


class RoomNotFound(RoomError):
    pass


class RoomFull(RoomError):
    pass


class RoomAlreadyStarted(RoomError):
    pass


def _room_key(code: str) -> str:
    return f"room:{code}"


def _players_key(code: str) -> str:
    return f"room:{code}:players"


def _sid_key(sid: str) -> str:
    return f"sid:{sid}"


async def _generate_unique_code(r) -> str:
    for _ in range(20):
        code = "".join(random.choices(ROOM_CODE_CHARS, k=settings.room_code_length))
        if not await r.exists(_room_key(code)):
            return code
    # Astronomically unlikely at this alphabet/length, but fail loudly
    # rather than silently handing out a colliding code.
    raise RuntimeError("Could not generate a unique room code after 20 attempts")


async def create_room(sid: str, player_id: str, username: str, avatar_config: dict) -> str:
    """Create a new room with `player_id` as host. Returns the room code."""
    r = get_redis()
    code = await _generate_unique_code(r)
    now = datetime.now(timezone.utc).isoformat()

    player_state = {
        "player_id": player_id,
        "username": username,
        "avatar_config": json.dumps(avatar_config),
        "is_host": "1",
        "status": "idle",
        "score": "0",
        "sid": sid,
    }

    pipe = r.pipeline()
    pipe.hset(_room_key(code), mapping={"status": "lobby", "host_player_id": player_id, "created_at": now})
    pipe.expire(_room_key(code), ROOM_TTL_SECONDS)
    pipe.hset(_players_key(code), player_id, json.dumps(player_state))
    pipe.expire(_players_key(code), ROOM_TTL_SECONDS)
    pipe.set(_sid_key(sid), json.dumps({"player_id": player_id, "room_code": code}), ex=ROOM_TTL_SECONDS)
    await pipe.execute()

    return code


async def join_room(sid: str, room_code: str, player_id: str, username: str, avatar_config: dict) -> None:
    """
    Add a player to an existing room, or update their sid if they're
    reconnecting (same player_id already in the room - keeps their score
    and host status intact rather than treating a refresh as a new join).
    """
    r = get_redis()
    room = await r.hgetall(_room_key(room_code))
    if not room:
        raise RoomNotFound(room_code)
    if room.get("status") != "lobby":
        raise RoomAlreadyStarted(room_code)

    players_raw = await r.hgetall(_players_key(room_code))

    if player_id in players_raw:
        existing = json.loads(players_raw[player_id])
        existing["sid"] = sid
        await r.hset(_players_key(room_code), player_id, json.dumps(existing))
    else:
        if len(players_raw) >= settings.max_players_per_room:
            raise RoomFull(room_code)
        new_player = {
            "player_id": player_id,
            "username": username,
            "avatar_config": json.dumps(avatar_config),
            "is_host": "0",
            "status": "idle",
            "score": "0",
            "sid": sid,
        }
        await r.hset(_players_key(room_code), player_id, json.dumps(new_player))

    await r.set(_sid_key(sid), json.dumps({"player_id": player_id, "room_code": room_code}), ex=ROOM_TTL_SECONDS)


async def get_room_state(room_code: str) -> dict | None:
    """Full snapshot of a room, shaped to match schemas.room.RoomStateOut."""
    r = get_redis()
    room = await r.hgetall(_room_key(room_code))
    if not room:
        return None

    players_raw = await r.hgetall(_players_key(room_code))
    players = []
    for raw in players_raw.values():
        p = json.loads(raw)
        players.append({
            "player_id": p["player_id"],
            "username": p["username"],
            "avatar_config": json.loads(p["avatar_config"]),
            "is_host": p.get("is_host") == "1",
            "status": p.get("status", "idle"),
            "score": int(p.get("score", 0)),
        })

    return {
        "room_code": room_code,
        "status": room.get("status", "lobby"),
        "host_player_id": room.get("host_player_id"),
        "players": players,
    }


async def leave_room_by_sid(sid: str) -> dict | None:
    """
    Remove whichever player this socket id belonged to - used for both an
    explicit `leave_room` event and an abrupt disconnect, since from the
    server's perspective they're the same cleanup.

    Returns None if this sid wasn't tracked (never joined a room, or was
    already cleaned up). Otherwise returns enough info for the socket
    layer to broadcast what happened:
        {room_code, player_id, room_deleted, new_host_id}
    """
    r = get_redis()
    sid_raw = await r.get(_sid_key(sid))
    if not sid_raw:
        return None

    sid_data = json.loads(sid_raw)
    player_id, room_code = sid_data["player_id"], sid_data["room_code"]
    await r.delete(_sid_key(sid))

    players_raw = await r.hgetall(_players_key(room_code))
    if player_id not in players_raw:
        return None  # already removed - e.g. duplicate disconnect events

    await r.hdel(_players_key(room_code), player_id)
    remaining = await r.hgetall(_players_key(room_code))

    room_deleted = False
    new_host_id = None

    if not remaining:
        # Last player out - nothing left to keep around for.
        await r.delete(_room_key(room_code))
        await r.delete(_players_key(room_code))
        room_deleted = True
    else:
        room = await r.hgetall(_room_key(room_code))
        if room.get("host_player_id") == player_id:
            # Host left mid-lobby - promote one of the remaining players.
            # NOTE: Redis hash field order is not a reliable proxy for
            # join order once fields have been added/removed (confirmed
            # by testing - it does not consistently pick the earliest
            # joiner). This is an arbitrary-but-deterministic choice among
            # remaining players, not a "longest in the room" guarantee. If
            # host succession by seniority ever matters, track a
            # `joined_at` timestamp per player explicitly instead of
            # relying on hash iteration order.
            new_host_id = next(iter(remaining))
            new_host_data = json.loads(remaining[new_host_id])
            new_host_data["is_host"] = "1"
            await r.hset(_players_key(room_code), new_host_id, json.dumps(new_host_data))
            await r.hset(_room_key(room_code), "host_player_id", new_host_id)

    return {
        "room_code": room_code,
        "player_id": player_id,
        "room_deleted": room_deleted,
        "new_host_id": new_host_id,
    }


async def is_host(room_code: str, player_id: str) -> bool:
    r = get_redis()
    host_id = await r.hget(_room_key(room_code), "host_player_id")
    return host_id == player_id
