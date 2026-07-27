"""
Round lifecycle: starting a game, advancing through the shuffled letter
queue, collecting draft answers, and locking a round the instant the first
player signals Done - immediately, no grace period, per spec.

Redis holds the live, in-progress round state (current letter, categories,
lock flag, and each player's not-yet-persisted answers) - see
services/room_manager.py's module docstring for why live state lives in
Redis rather than Postgres. Postgres only gets written once a round is
actually LOCKED (see `_persist_round_to_db`), as a checkpoint - matching
the split explained in database/session.py vs database/redis_client.py.

NOT done here: validation (local dataset lookup + Groq challenge
fallback) and scoring. Every persisted Answer gets status PENDING (or
BLANK if empty) here; Phase 4/5 build the real validation and scoring on
top of what this phase persists.
"""
import json
import logging
from datetime import datetime, timezone

from database.redis_client import get_redis
from database.session import AsyncSessionLocal
from services import category_selector, letter_generator, room_manager

from config import settings

logger = logging.getLogger("npat.game_manager")


class GameError(Exception):
    """Base class for game errors the socket layer translates into an `error` event."""


class NotHost(GameError):
    pass


class NotEnoughPlayers(GameError):
    pass


class GameAlreadyStarted(GameError):
    pass


class GameNotInProgress(GameError):
    pass


class RoundAlreadyLocked(GameError):
    pass


def _game_key(code: str) -> str:
    return f"game:{code}"


def _answers_key(code: str) -> str:
    return f"game:{code}:answers"


async def start_game(room_code: str, requesting_player_id: str) -> dict:
    """
    Validates the requester is host and there are enough players, shuffles
    the letter order, flips the room to in_progress, and starts round 1.
    Returns the same shape as start_next_round()'s non-finished case.
    """
    if not await room_manager.is_host(room_code, requesting_player_id):
        raise NotHost(requesting_player_id)

    room_state = await room_manager.get_room_state(room_code)
    if room_state is None:
        raise room_manager.RoomNotFound(room_code)
    if room_state["status"] != "lobby":
        raise GameAlreadyStarted(room_code)
    if len(room_state["players"]) < settings.min_players_to_start:
        raise NotEnoughPlayers(room_code)

    r = get_redis()
    letters = letter_generator.shuffle_letters()

    pipe = r.pipeline()
    pipe.hset(_game_key(room_code), mapping={
        "round_number": "0",
        "locked": "0",
        "letters_queue": json.dumps(letters),
    })
    pipe.expire(_game_key(room_code), room_manager.ROOM_TTL_SECONDS)
    await pipe.execute()
    await room_manager.set_room_status(room_code, "in_progress")

    return await start_next_round(room_code)


async def start_next_round(room_code: str) -> dict:
    """
    Pops the next letter and starts a new round. If the letter queue is
    already empty, flips the room to finished and returns
    {"finished": True} instead - the caller (socket handler) is
    responsible for emitting `game_finished` in that case and not calling
    this again.
    """
    r = get_redis()
    game = await r.hgetall(_game_key(room_code))
    if not game:
        raise GameNotInProgress(room_code)

    letters_queue = json.loads(game.get("letters_queue", "[]"))
    if not letters_queue:
        await room_manager.set_room_status(room_code, "finished")
        return {"finished": True}

    next_letter = letters_queue.pop(0)
    categories = category_selector.select_categories()
    round_number = int(game.get("round_number", "0")) + 1

    pipe = r.pipeline()
    pipe.hset(_game_key(room_code), mapping={
        "round_number": str(round_number),
        "current_letter": next_letter,
        "categories": json.dumps(categories),
        "locked": "0",
        "letters_queue": json.dumps(letters_queue),
    })
    pipe.delete(_answers_key(room_code))  # clear previous round's drafts
    await pipe.execute()

    await room_manager.reset_all_player_statuses(room_code, "idle")

    return {
        "finished": False,
        "round_number": round_number,
        "letter": next_letter,
        "categories": categories,
        "letters_remaining": len(letters_queue),
    }


async def submit_answers(room_code: str, player_id: str, answers: list[dict]) -> None:
    """
    Save/update a player's draft answers for the current round. Safe to
    call multiple times before the round locks (e.g. periodic client-side
    autosave); has no effect on locking and isn't broadcast to other
    players - only the eventual locked reveal is.
    """
    r = get_redis()
    game = await r.hgetall(_game_key(room_code))
    if not game:
        raise GameNotInProgress(room_code)
    if game.get("locked") == "1":
        raise RoundAlreadyLocked(room_code)

    answers_map = {a["category"]: a.get("text", "").strip() for a in answers}
    await r.hset(_answers_key(room_code), player_id, json.dumps(answers_map))
    await room_manager.set_player_status(room_code, player_id, "typing")


async def player_done(room_code: str, player_id: str, answers: list[dict] | None = None) -> dict:
    """
    The first player to press Done locks the round for everyone,
    immediately, with no grace period. Whatever each player has saved via
    submit_answers (or passes here directly as their own final answers)
    at this exact instant becomes their locked submission; anyone who
    submitted nothing gets a blank answer for every category.

    Persists the locked round to Postgres before returning - see
    _persist_round_to_db.
    """
    r = get_redis()
    game = await r.hgetall(_game_key(room_code))
    if not game:
        raise GameNotInProgress(room_code)
    if game.get("locked") == "1":
        raise RoundAlreadyLocked(room_code)

    if answers is not None:
        answers_map = {a["category"]: a.get("text", "").strip() for a in answers}
        await r.hset(_answers_key(room_code), player_id, json.dumps(answers_map))

    await r.hset(_game_key(room_code), "locked", "1")
    await room_manager.set_player_status(room_code, player_id, "done")

    round_number = int(game["round_number"])
    letter = game["current_letter"]
    categories = json.loads(game["categories"])

    room_state = await room_manager.get_room_state(room_code)
    all_players = {p["player_id"]: p for p in room_state["players"]}

    raw_answers = await r.hgetall(_answers_key(room_code))
    revealed = []
    per_player_answers: dict[str, dict[str, str]] = {}

    for pid, pinfo in all_players.items():
        player_answers = json.loads(raw_answers.get(pid, "{}"))
        per_player_answers[pid] = player_answers
        for category in categories:
            text = player_answers.get(category, "")
            revealed.append({
                "player_id": pid,
                "username": pinfo["username"],
                "category": category,
                "text": text,
                "status": "blank" if not text else "pending",
                "points_awarded": 0,
                "was_challenged": False,
            })

    # The round is already locked in Redis at this point - irreversibly,
    # per spec (no grace period, no undo). A Postgres write failure here
    # (bad player_id, transient DB unavailability, etc.) must not prevent
    # players from seeing their round results: Redis is already the
    # source of truth for "this round is locked and these are the
    # answers" for live gameplay. Losing the durable copy of one round is
    # recoverable later; leaving every player's client hanging on a round
    # that will never resolve is not. So this is logged, not raised.
    try:
        await _persist_round_to_db(
            room_code, room_state["host_player_id"], round_number, letter, categories, per_player_answers
        )
    except Exception:
        logger.exception(
            "Failed to persist round %s for room %s to Postgres - round is still "
            "locked and playable in Redis, but this round's data was not saved.",
            round_number, room_code,
        )

    return {
        "round_number": round_number,
        "locked_by_player_id": player_id,
        "answers": revealed,
    }


async def _persist_round_to_db(
    room_code: str,
    host_player_id: str,
    round_number: int,
    letter: str,
    categories: list[str],
    per_player_answers: dict[str, dict[str, str]],
) -> None:
    """
    Writes the just-locked round and its raw answers to Postgres. Every
    Answer is stored with status PENDING (or BLANK if the text was empty)
    - Phase 4 fills in real validation status, Phase 5 fills in scoring.
    """
    from sqlalchemy import select

    from models import Answer, AnswerStatus, Round, Room, RoomStatus

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Room).where(Room.room_code == room_code))
        room_row = result.scalar_one_or_none()

        if room_row is None:
            # No ORM Room row exists yet - Phase 2's room creation is
            # Redis-only (the lobby doesn't need Postgres to function),
            # so the first row gets written here, at first-round-lock
            # time, rather than adding a DB write to the hot path of
            # every room creation. host_player_id must reference an
            # existing players.id row (via POST /api/players) - see the
            # FK on Room.host_player_id in models/game.py.
            room_row = Room(room_code=room_code, host_player_id=host_player_id, status=RoomStatus.IN_PROGRESS)
            session.add(room_row)
            await session.flush()  # assign room_row.id without committing yet

        round_row = Round(
            room_id=room_row.id,
            round_number=round_number,
            letter=letter,
            categories=categories,
            locked_at=datetime.now(timezone.utc),
        )
        session.add(round_row)
        await session.flush()  # assign round_row.id

        for player_id, answers_map in per_player_answers.items():
            for category in categories:
                text = answers_map.get(category, "")
                session.add(Answer(
                    round_id=round_row.id,
                    player_id=player_id,
                    category=category,
                    text=text,
                    status=AnswerStatus.BLANK if not text else AnswerStatus.PENDING,
                ))

        await session.commit()
