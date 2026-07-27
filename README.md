# NPAT Backend — Phases 1, 2 & 3: Foundation + Rooms + Game Engine

Real-time multiplayer Name-Place-Animal-Thing backend.
- **Phase 1** laid the foundation: project structure, config, DB models,
  Pydantic schemas, and a working FastAPI + Socket.IO app.
- **Phase 2** added the room lifecycle: create/join/leave a room in real
  time, backed by Redis.
- **Phase 3** (this update) adds the actual game engine: letter shuffle,
  category selection, round lifecycle, and immediate locking on the first
  player's Done — tested against a real local Postgres + Redis + running
  server, not mocks (details below).

## What's in these phases

```
backend/
├── main.py                  # FastAPI + Socket.IO combined ASGI entrypoint
├── config.py                 # Settings (env-driven), incl. scoring/game tuning
├── requirements.txt
├── requirements-dev.txt       # only for test_connection.py / test_socket_flow.py
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
│   ├── round.py                 # UPDATED: player_done can now carry final answers
│   └── socket_events.py
├── services/                  # game logic, independent of the transport layer
│   ├── room_manager.py          # Redis-backed room/player state
│   ├── letter_generator.py      # NEW: shuffles all 26 letters once per game
│   ├── category_selector.py     # NEW: picks 4-5 random categories per round
│   └── game_manager.py          # NEW: round lifecycle orchestrator - the core of Phase 3
├── api/
│   └── players.py              # POST/GET /api/players (create + fetch profile)
└── sockets/
    ├── server.py                # AsyncServer + Redis-backed manager
    ├── connection.py            # connect/disconnect - disconnect delegates to rooms.handle_departure
    ├── rooms.py                 # create_room / join_room / leave_room event handlers
    └── gameplay.py               # NEW: start_game / submit_answers / player_done / next_round
```

### What Phase 3 actually does
- `start_game` (host only) — shuffles all 26 letters, flips the room to
  `in_progress`, deals round 1.
- Each round: server picks the next letter off the shuffled queue and
  4-5 random categories from the pool.
- `submit_answers` — a player's draft answers, saved to Redis. Callable
  any number of times before the round locks; not broadcast to other
  players (only the eventual locked reveal is).
- `player_done` — **locks the round immediately for everyone**, no grace
  period, matching the spec exactly (an explicit choice confirmed before
  this phase started). Whatever each player had saved via
  `submit_answers` (or passes directly with their Done) becomes their
  frozen submission; anyone who submitted nothing gets blank answers. The
  locked round and every answer get written to Postgres at this point,
  with status `PENDING` (or `BLANK`) — no validation or scoring yet,
  that's Phase 4/5.
- `next_round` (host only, **not** in the original spec's event list —
  added because the automatic advance-after-stats flow depends on Phase
  5's achievement engine, which doesn't exist yet) — deals the next
  letter, or emits `game_finished` once all 26 have been used.
- Trying to join a room after it's started, submit/Done after a round is
  already locked, or a non-host trying to start/advance the game all
  produce a clean `error` event rather than corrupting state.

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
  rounds/answers, final results. Written at checkpoints — specifically,
  the instant a round locks — not on every event.
- **Redis** (`services/room_manager.py`, `services/game_manager.py`) holds
  live, fast-changing state: who's in a room, host status, the current
  letter/categories, draft answers before a round locks. This is also why
  Socket.IO uses `AsyncRedisManager` — it lets events fan out correctly
  even across multiple backend worker processes.

### A design tradeoff worth knowing about
`Room.host_player_id` in Postgres has a real foreign-key constraint to
`players.id` (see `models/game.py`). This means a room's first Postgres
row (written at first-round-lock time — Phase 2's room creation stays
Redis-only) requires the host to have actually gone through
`POST /api/players` first. If a client ever sent game events with a
`player_id` Postgres doesn't know about, that DB write would fail — I
caught this during testing (details below) and made a deliberate choice:
**a Postgres persistence failure is logged, not raised.** The round stays
locked and playable in Redis regardless, because from a player's chair,
a round that never resolves is worse than a round whose data silently
didn't get saved. Worth knowing if you ever see a
"Failed to persist round... to Postgres" warning in your logs — it means
gameplay kept going, but that round's history didn't get saved.

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

## How this was tested

**Phase 2** (rooms): I installed a local `redis-server` in the sandbox and
ran real integration tests against it — full room lifecycle (create, join,
reconnect, fill to capacity, host leaves, last player leaves), then the
actual Socket.IO handlers with a real server + real client. That caught a
real bug: `sio.enter_room()`/`sio.leave_room()` are coroutines on
`AsyncServer` and need `await` — without it, the calls silently no-op'd
(Python just warns rather than erroring), so a player's Redis state was
correct but they never actually joined the Socket.IO broadcast group.
Fixed in `sockets/rooms.py`.

**Phase 3** (game engine): this time I installed a local **Postgres**
too, since round-locking actually writes to it. Ran real migrations
against it, then played a full game through **real REST calls + real
Socket.IO clients** end-to-end: created two real players via
`POST /api/players`, created/joined a room, `start_game`, one player
saving a draft via `submit_answers`, the other pressing Done with answers
bundled directly, confirmed the round locked immediately (no grace
period) with both players' answers correctly captured, advanced to round
2 with a new letter/categories, and confirmed a non-host is rejected from
advancing the round. Then queried Postgres directly to confirm what
actually landed there — not just what the socket events claimed.

That last step caught a real bug: the persisted `Room.host_player_id` was
wrong (it was picking an arbitrary player from a dict instead of asking
who the actual host was — confirmed by the DB literally showing the
guest's ID as host). Fixed to pass the real host id through explicitly.
It also surfaced the FK-constraint/persistence-failure tradeoff described
above, which led to the "log, don't raise" decision in `player_done`.

I also directly tested the edge cases hardest to hit by playing an entire
26-round game manually: the letter queue reaching empty (`game_finished`
path, and confirmed calling `next_round` again afterward doesn't error),
late joins being rejected once a game has started, double-`start_game`
being rejected, and `submit_answers`/`player_done` both being correctly
rejected once a round is already locked.

What I couldn't test: a client actually typing into a UI and clicking
buttons — there's no frontend yet. Everything above was driven by
scripted REST/socket calls, which covers the server's correctness but not
things like network latency handling or UI-side state management once
the frontend exists.

## What's NOT here yet (later phases)
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
