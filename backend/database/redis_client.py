"""
Redis connection used for ephemeral, server-authoritative game/room state.

Why Redis and not just Postgres for live state:
- Rooms/rounds change many times per second across concurrent players.
- State needs to survive a single worker process restart in a multi-worker
  deployment (Socket.IO also uses a Redis-backed manager for this reason,
  see socket/server.py).
- Postgres remains the system of record for persisted results (players,
  final scores, completed games) - see models/.
"""
import redis.asyncio as redis

from config import settings

redis_pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)


def get_redis() -> redis.Redis:
    """Return a Redis client bound to the shared connection pool."""
    return redis.Redis(connection_pool=redis_pool)
