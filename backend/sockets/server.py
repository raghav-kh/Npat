"""
Socket.IO server instance, shared by every event handler module.

Uses a Redis-backed AsyncRedisManager rather than the default in-memory
manager. This means:
- If you run multiple uvicorn workers/instances behind a load balancer,
  events emitted from one worker still reach clients connected to another.
- It reuses the same Redis your room/game state already lives in
  (database/redis_client.py), so no extra infra is needed.

Event handlers themselves live in sockets/rooms.py, sockets/gameplay.py etc.
(added in later phases) and get registered onto this `sio` instance.
"""
import socketio

from config import settings

mgr = socketio.AsyncRedisManager(settings.redis_url)

sio = socketio.AsyncServer(
    async_mode="asgi",
    client_manager=mgr,
    cors_allowed_origins=settings.cors_origin_list,
)


def build_combined_app(fastapi_app):
    """
    Wrap the FastAPI app so Socket.IO handles /socket.io/* and everything
    else falls through to FastAPI. This is the pattern python-socketio
    recommends (other_asgi_app) rather than mounting at "/", since a
    root mount can shadow FastAPI's own routing order in edge cases.
    """
    return socketio.ASGIApp(sio, other_asgi_app=fastapi_app, socketio_path="socket.io")
