"""
Async SQLAlchemy engine + session factory.

Configured for Supabase Postgres (or any PgBouncer-fronted Postgres) via
asyncpg, which needs adjustments beyond a plain local connection:

1. TLS without certificate verification - Supabase's connection pooler
   (Supavisor) terminates TLS using its own certificate, which is not
   signed by a public CA. That means there's no chain for the OS trust
   store *or* certifi's bundle to verify it against - you'll see
   "self-signed certificate in certificate chain" regardless of which CA
   bundle you point at, because the problem isn't a missing root cert,
   it's that there genuinely isn't a publicly-verifiable one. The traffic
   is still encrypted (nothing is sent in plaintext); what's disabled is
   confirming the server's identity against a certificate authority. This
   is the standard, documented approach for connecting asyncpg to
   Supabase's pooler. If you switch to Supabase's *direct* connection
   (port 5432, bypassing the pooler) it typically presents a properly
   CA-signed certificate and you could re-enable verification there.
2. Two separate prepared-statement caches must both be disabled - it's
   not enough to disable just one:
     - `statement_cache_size=0` disables asyncpg's own cache.
     - `prepared_statement_cache_size=0` disables a *second*, independent
       cache SQLAlchemy's asyncpg dialect keeps on top of asyncpg, which
       assigns its own stable statement names (e.g. "__asyncpg_stmt_1__")
       across executions. Under Supabase's transaction-mode pooler, a
       name assigned in one logical transaction can collide with the same
       name already prepared on a *different* physical backend connection
       the pooler hands you next time - producing
       `DuplicatePreparedStatementError` even with asyncpg's own cache
       off, because the second cache is what's generating the reused name.
   Both are required. If you switch to Supabase's direct connection
   (port 5432, no pooler) both are harmless to leave on.
3. `poolclass=NullPool` - stops SQLAlchemy from layering its own
   connection pool on top of a connection that Supabase's pooler is
   already managing underneath. This is the pattern SQLAlchemy's own docs
   recommend when connecting through PgBouncer in transaction mode.

Even with all three of the above, Supabase's Transaction pooler
(Supavisor) can still intermittently throw `DuplicatePreparedStatementError`
during a long sequence of DDL statements in one session (i.e. Alembic
migrations) - it doesn't fully clear prepared-statement state between
pooled sessions the way classic PgBouncer does. This is a known Supavisor
limitation, not a config mistake. The fix is NOT to keep tightening this
config further - it's to not run migrations through the Transaction
pooler at all. See `config.migrations_database_url` and
`alembic/env.py`: migrations use Supabase's Session pooler (port 5432) or
direct connection instead, while the app keeps using the Transaction
pooler here for its normal runtime queries, where pooling many short-lived
connections is actually the right trade-off.
"""
import ssl

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from config import settings


def _connect_args(url: str) -> dict:
    if not url.startswith("postgresql"):
        return {}
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    return {
        "ssl": ssl_context,
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    }


def _pool_kwargs(url: str) -> dict:
    """NullPool is only appropriate for the pooled Supabase connection
    (port 6543). For sqlite (local/dev) or a direct/session Postgres
    connection, SQLAlchemy's default pooling is fine and preferable."""
    if not url.startswith("postgresql"):
        return {"pool_pre_ping": True}
    return {"poolclass": NullPool}


def build_engine(url: str) -> AsyncEngine:
    """
    Build an async engine with the SSL/pooler-safety config above applied,
    against whichever URL is passed in. Used both for the app's own engine
    (below, against `settings.database_url`) and by Alembic (against
    `settings.migrations_database_url`, a different connection meant to
    avoid the Transaction pooler's prepared-statement issues - see
    alembic/env.py).
    """
    return create_async_engine(
        url,
        echo=settings.environment == "development",
        future=True,
        connect_args=_connect_args(url),
        **_pool_kwargs(url),
    )


engine = build_engine(settings.database_url)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


async def get_db():
    """FastAPI dependency that yields a DB session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
