"""
Per-room, per-player final results. One row per player per room, written
when a game finishes. Kept separate from Player so a player's identity
isn't coupled to any single game's outcome.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from database.session import Base


class RoomResult(Base):
    __tablename__ = "room_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id"), nullable=False)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id"), nullable=False)

    total_score: Mapped[int] = mapped_column(Integer, default=0)
    placement: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 = winner

    # Snapshot of achievements unlocked this game, e.g. ["speed_demon", "lucky_guess"]
    achievements_unlocked: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
