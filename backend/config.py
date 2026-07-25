"""
Centralized application configuration.
Loaded once from environment variables / .env file.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    # This should be Supabase's Transaction pooler URL (port 6543) - it's
    # what the running app uses for normal query traffic, where pooling
    # many short-lived connections matters.
    database_url: str = "postgresql+asyncpg://npat_user:npat_pass@localhost:5432/npat_db"

    # Used only by Alembic for migrations. Point this at Supabase's Session
    # pooler (port 5432) or the direct connection string instead of the
    # Transaction pooler. The Transaction pooler (Supavisor) doesn't fully
    # clear prepared-statement state between pooled sessions, which causes
    # intermittent `DuplicatePreparedStatementError` during schema changes -
    # harmless for the app's normal short queries, but migrations run many
    # sequential DDL statements in one session and hit it reliably. If left
    # blank, falls back to `database_url`.
    migrations_database_url: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Groq
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    # App
    environment: str = "development"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Game tuning
    room_code_length: int = 5
    max_players_per_room: int = 12
    min_players_to_start: int = 2
    round_lock_grace_seconds: int = 3
    categories_per_round_min: int = 4
    categories_per_round_max: int = 5

    # Scoring
    points_valid_unique: int = 10
    points_duplicate: int = 0
    points_invalid: int = 0
    points_blank: int = 0

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
