# NPAT Backend — Phase 1: Foundation

Real-time multiplayer Name-Place-Animal-Thing backend. This phase lays the
foundation everything else builds on: project structure, config, DB models,
Pydantic schemas, and a working (but minimal) FastAPI + Socket.IO app that
boots cleanly.

## What's in this phase

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
│   └── round.py
├── api/
│   └── players.py              # POST/GET /api/players (create + fetch profile)
└── sockets/                   # (named `sockets`, NOT `socket` — see note below)
    ├── server.py                # AsyncServer + Redis-backed manager
    └── connection.py            # connect/disconnect logging (room events land in Phase 2)
```

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
- **Redis** (`database/redis_client.py`) will hold live, fast-changing state
  in Phase 2/3: who's in a room right now, current round timer, who's typing,
  locked-but-not-yet-persisted answers. This is also why Socket.IO uses
  `AsyncRedisManager` — it lets events fan out correctly even across
  multiple backend worker processes.

## Setup (Supabase + Upstash — no Docker needed)

**1. Supabase (Postgres)**
- Create a project at supabase.com.
- Settings → Database → Connection string → copy the **Transaction pooler**
  string (port `6543`). It looks like:
  `postgresql://postgres.xxxx:[email protected]:6543/postgres`
- Change the scheme from `postgresql://` to `postgresql+asyncpg://`.
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

**Two things `database/session.py` already handles for you**, so you
shouldn't need to touch them: Supabase requires TLS (`ssl=True` passed to
asyncpg), and its pooler runs PgBouncer in transaction mode, which breaks
asyncpg's prepared-statement cache unless it's disabled
(`statement_cache_size=0`). If you ever see `prepared statement ... does
not exist` errors, that setting is the first thing to check.

I verified the connection logic inside the sandbox (engine builds
correctly against both Supabase-style and Upstash-style URLs, TLS is
auto-selected for `rediss://`, and full `CREATE TABLE` generation passes
against SQLite as a stand-in) — but I don't have network access to your
actual Supabase/Upstash instances from here, so `alembic upgrade head`
and the curl checks above are on you to run for real.

## What's NOT here yet (later phases)
- Room creation/joining logic + `sockets/rooms.py` events
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
