"""
Entrypoint. Combines:
- FastAPI app for stateless REST endpoints (player profile CRUD, health)
- Socket.IO ASGI app for real-time room/game events

Run with: uvicorn main:asgi_app --reload
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from api.players import router as players_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Nothing to warm up yet - Postgres is only touched by REST endpoints
    # (api/players.py) and, from Phase 3 onward, by game_manager writing
    # completed rounds/results. Redis (room state) is connected lazily via
    # database/redis_client.get_redis() on first use.
    yield


app = FastAPI(title="NPAT Game API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(players_router)


@app.get("/health")
async def health():
    return {"status": "ok", "environment": settings.environment}


# Importing these registers their @sio.event / @sio.on handlers as a side
# effect (connection.py: connect/disconnect; rooms.py: create_room/
# join_room/leave_room). Socket.IO then wraps the FastAPI app: /socket.io/*
# is handled by Socket.IO, every other path falls through to FastAPI.
from sockets import connection, rooms  # noqa: E402,F401
from sockets.server import build_combined_app  # noqa: E402

# Uvicorn target
asgi_app = build_combined_app(app)
