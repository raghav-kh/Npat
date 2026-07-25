"""
Player: a lightweight identity, not an authenticated account.

No password, no email. A player is created client-side (and mirrored here)
so the same username+avatar can be reused across games. The client stores
the returned player id locally (e.g. localStorage) and sends it on
subsequent visits instead of re-registering.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from database.session import Base


class Player(Base):
    __tablename__ = "players"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(20), nullable=False)

    # Avatar is stored as a config dict (hair, eyes, skin tone, etc.) rather
    # than a rendered image - the SVG is generated on the fly by
    # services/avatar_service.py from this config. Keeps storage tiny and
    # makes avatars trivially re-themeable later.
    avatar_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return f"<Player {self.username} ({self.id})>"
