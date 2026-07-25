"""
Standalone connection test - run this directly to debug DATABASE_URL
issues without going through Alembic or the full app.

Usage:
    python test_connection.py

Reads DATABASE_URL from your .env (same as the app does). If your password
has special characters, this script also prints a properly URL-encoded
version of your connection string you can paste back into .env.
"""
import asyncio
import re
import sys
from urllib.parse import quote, urlsplit, urlunsplit

from dotenv import load_dotenv
import os

load_dotenv()


def suggest_encoded_url(raw_url: str) -> str | None:
    """
    If DATABASE_URL has an unencoded special character in the password,
    build a corrected version. Returns None if nothing needed fixing.
    """
    match = re.match(r"^(postgresql(?:\+asyncpg)?://)([^:]+):(.+)@([^/]+)(/.*)$", raw_url)
    if not match:
        return None
    scheme, user, password, hostpart, rest = match.groups()
    encoded_password = quote(password, safe="")
    if encoded_password == password:
        return None  # nothing to fix
    return f"{scheme}{user}:{encoded_password}@{hostpart}{rest}"


async def main():
    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        print("DATABASE_URL is not set - check your .env file and that you're running this from backend/")
        sys.exit(1)

    fixed = suggest_encoded_url(raw_url)
    if fixed:
        print("⚠️  Your password appears to contain characters that need URL-encoding.")
        print("    Try replacing DATABASE_URL in your .env with:\n")
        print(f"    DATABASE_URL={fixed}\n")

    import asyncpg

    # Parse pieces out manually so we can call asyncpg directly (bypasses
    # SQLAlchemy entirely - fastest way to confirm raw credentials work).
    parts = urlsplit(raw_url.replace("postgresql+asyncpg://", "postgresql://"))
    user = parts.username
    password = parts.password
    host = parts.hostname
    port = parts.port or 5432
    database = (parts.path or "/postgres").lstrip("/")

    print(f"Connecting to {host}:{port} as user={user!r} db={database!r} ...")

    try:
        conn = await asyncpg.connect(
            user=user,
            password=password,
            host=host,
            port=port,
            database=database,
            ssl="require",
        )
        version = await conn.fetchval("SELECT version()")
        print("✅ Connected successfully.")
        print(version)
        await conn.close()
    except Exception as e:
        print(f"❌ Connection failed: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
