# NPAT Backend — Phases 1 & 2: Foundation + Room Manager

Real-time multiplayer Name-Place-Animal-Thing backend.
- **Phase 1** laid the foundation: project structure, config, DB models,
  Pydantic schemas, and a working FastAPI + Socket.IO app.
- **Phase 2** (this update) adds the room lifecycle: create/join/leave a
  room in real time, backed by Redis, with a full automated test suite
  run against a real Redis instance (details below).

## What's in these phases

```
backend/
├── main.py                  # FastAPI + Socket.IO combined ASGI entrypoint
├── config.py                 # Settings (env-driven), incl. scoring/game tuning
├── requirements.txt
├── .env.example               # copy to .env and fill in
├── alembic/                   # migrations (async, autogenerate wired to models)
├── database/
│   ├── session.py              # async SQLAlchemy engine/session
│   └── redis_client.py         # Redis pool for live room/game state
├── models/                    # SQLAlchemy ORM (persisted records)
│   ├── player.py                # Player: username + avatar_config, no auth
│   ├── game.py                  # Room, Round, Answer
│   └── results.py               # RoomResult: final per-player scores
├── schemas/                   # Pydantic request/response models
│   ├── player.py
│   ├── room.py
│   ├── round.py
│   └── socket_events.py         # NEW: validates create_room/join_room/leave_room payloads
├── services/                  # NEW: game logic, independent of the transport layer
│   └── room_manager.py          # Redis-backed room/player state - the source of truth
├── api/
│   └── players.py              # POST/GET /api/players (create + fetch profile)
└── sockets/                   # (named `sockets`, NOT `socket` — see note below)
    ├── server.py                # AsyncServer + Redis-backed manager
    ├── connection.py            # connect/disconnect - disconnect delegates to rooms.handle_departure
    └── rooms.py                 # NEW: create_room / join_room / leave_room event handlers
```

### What Phase 2 actually does
- `create_room` — generates a 5-character room code (ambiguous characters
  like `O`/`0`, `I`/`1` excluded), makes the creator host, replies with
  `room_created`.
- `join_room` — validates the room exists, isn't full, and hasn't started;
  broadcasts `player_joined` (full room state) to everyone including the
  joiner. Rejoining with the same `player_id` (e.g. a page refresh) is
  treated as a reconnect — it updates their socket id in place rather than
  duplicating them or resetting their score.
- `leave_room` (explicit) and an abrupt disconnect both route through the
  same `room_manager.leave_room_by_sid` cleanup — whichever way a player
  leaves, the room state ends up consistent. If the host leaves, another
  player is promoted; if the room empties out, it's deleted from Redis.
- Bad payloads (missing username, etc.) get a clean `error` event with a
  specific message instead of a crash — every handler validates through
  `schemas/socket_events.py` first.

### Why no auth
Per the spec, players are just `username + avatar`, stored client-side
(localStorage) and mirrored in Postgres via `POST /api/players` so the same
identity can be reused across games. No passwords, no JWT.

### Why `sockets/` and not `socket/`
Python has a built-in `socket` module used internally by asyncio, Redis,
etc. A local package named `socket` would shadow it and cause subtle,
hard-to-diagnose failures. Named it `sockets/` instead — keep this in mind
if you add files here later.

### State split: Postgres vs Redis
- **Postgres** (`models/`) is the system of record: players, completed
  rounds/answers, final results. Written at checkpoints, not on every event.
- **Redis** (`services/room_manager.py`) holds live, fast-changing state:
  who's in a room right now, host status, reconnect handling. Round
  timers, who's typing, and locked-but-not-yet-persisted answers land in
  Phase 3. This is also why Socket.IO uses `AsyncRedisManager` — it lets
  events fan out correctly even across multiple backend worker processes.

## Setup (Supabase + Upstash — no Docker needed)

**1. Supabase (Postgres)**
- Create a project at supabase.com.
- Settings → Database → Connection string → copy the **Transaction pooler**
  string (port `6543`) for `DATABASE_URL`. It looks like:
  `postgresql://postgres.xxxx:[email protected]:6543/postgres`
- Also copy the **Session pooler** string (same page, port `5432`) for
  `MIGRATIONS_DATABASE_URL`. Alembic needs this one specifically —
  Supabase's Transaction pooler doesn't reliably support the back-to-back
  DDL statements a migration runs in one session (you'll see
  `DuplicatePreparedStatementError` if you point migrations at it), while
  it's the right choice for the app's normal runtime queries.
- For both: change the scheme from `postgresql://` to `postgresql+asyncpg://`.
  SQLAlchemy's async engine needs the driver named explicitly — Supabase's
  dashboard won't give you this part.

**2. Upstash (Redis)**
- Create a database at upstash.com (free tier, regional is fine).
- Copy the `rediss://` connection string (TLS) from the dashboard — not
  the plain `redis://` one.

**3. Configure and run**
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # paste in your Supabase DATABASE_URL, Upstash REDIS_URL, GROQ_API_KEY

alembic revision --autogenerate -m "init tables"
alembic upgrade head

uvicorn main:asgi_app --reload
```

Verify it's alive:
```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/players \
  -H "Content-Type: application/json" \
  -d '{"username": "Raghav", "avatar_config": {"hair": "short", "skin_tone": "#F1C27D"}}'
```

**What `database/session.py` already handles for you**, so you shouldn't
need to touch it: TLS against Supabase's pooler (which presents a
certificate with no public CA to verify, so verification is disabled
rather than attempted against the wrong trust store), and both layers of
prepared-statement caching that break under Supabase's Transaction pooler
(`statement_cache_size=0` and `prepared_statement_cache_size=0`, plus
`NullPool` so SQLAlchemy isn't pooling on top of an already-pooled
connection). Migrations use a separate `MIGRATIONS_DATABASE_URL` (Session
pooler) for the reason explained above — if you ever see
`DuplicatePreparedStatementError` specifically during `alembic upgrade`,
double check that env var is actually set and pointed at port `5432`, not
`6543`.

I verified the connection logic inside the sandbox (both engines build
correctly against Supabase-style URLs on their respective ports, TLS is
auto-selected for Upstash's `rediss://`, and full `CREATE TABLE` generation
passes against SQLite as a stand-in) — but I don't have network access to
your actual Supabase/Upstash instances from here, so `alembic upgrade
head` and the curl checks above are on you to run for real.

## How Phase 2 was tested

I don't have your actual Supabase/Upstash credentials, but Redis itself
doesn't need them — it's the same protocol everywhere. So instead of
skipping testing, I installed a local `redis-server` in the sandbox and
ran real integration tests against it (not mocks):

1. **`services/room_manager.py`** — a full scenario end-to-end: create a
   room, join a second player, reconnect that same player (confirmed no
   duplicate), fill the room to `MAX_PLAYERS_PER_ROOM` and confirm the
   next join raises `RoomFull`, confirm joining a nonexistent code raises
   `RoomNotFound`, have the host leave and confirm another player is
   promoted, then have everyone leave and confirm the room is deleted
   from Redis. All passed.
2. **`sockets/rooms.py`** — called the actual event handlers (not
   `room_manager` directly) with `sio.emit`/`enter_room`/`leave_room`
   mocked, to check the Socket.IO-specific wiring: correct events fire,
   `player_joined` broadcasts to the whole room, a malformed payload
   produces a clean `error` event instead of a crash, and disconnect
   cleanup produces the right `player_left` payload.
3. **`main.py`** — booted the full app (via `TestClient`, SQLite standing
   in for Postgres, real local Redis) and confirmed all five handlers
   (`create_room`, `join_room`, `leave_room`, `connect`, `disconnect`)
   are actually registered on the Socket.IO server.

What I couldn't test: a real network-level Socket.IO client hitting a
running server over an actual port — the sandbox doesn't keep background
processes alive between tool calls, so that layer is worth a quick manual
check on your end (e.g. with the Socket.IO client of your choice, or
Postman's Socket.IO support) once you're running this locally.

## What's NOT here yet (later phases)
- Letter shuffle, category selection, round lifecycle, locking (`services/`)
- Local dataset + Groq challenge validation (`services/validator.py`)
- Scoring + duplicate detection + achievement engine
- Avatar SVG generation (`services/avatar_service.py`)
- Frontend (React)

## Notes / things to double check on your end
- `GROQ_API_KEY` — I can't test the real Groq call from this sandbox (no
  network access to `api.groq.com` here), so double-check that once
  `services/validator.py` lands in Phase 4.
- `alembic upgrade head` needs your real Supabase instance reachable at
  `DATABASE_URL` — I verified the models generate correct DDL and that the
  engine/SSL/pooler config is right, but haven't run a migration against
  your actual Supabase project (no network access to it from here).
