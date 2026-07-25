"""
Alembic environment for an async SQLAlchemy engine (asyncpg).

Uses `settings.migrations_database_url` (falling back to `database_url` if
unset) rather than the app's own `engine` from database/session.py.

Why not just reuse the app's engine: the app's engine is configured for
Supabase's Transaction pooler (port 6543), which is right for a running
server handling many short queries, but Supavisor doesn't fully clear
prepared-statement state between pooled sessions, and a migration issues
many DDL statements in a row on one session - reliably triggering
DuplicatePreparedStatementError. Point `migrations_database_url` at
Supabase's Session pooler (port 5432) or the direct connection instead;
`build_engine()` (database/session.py) still applies the same SSL config
either way, so this is the only place migrations differ from the app.
"""
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy.engine import Connection

from alembic import context

# Make `backend/` importable regardless of where alembic is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings  # noqa: E402
from database.session import build_engine  # noqa: E402
from models import Base  # noqa: E402  (imports all models as a side effect)

migrations_url = settings.migrations_database_url or settings.database_url
engine = build_engine(migrations_url)

config = context.config
config.set_main_option("sqlalchemy.url", migrations_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=migrations_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio
    asyncio.run(run_migrations_online())
