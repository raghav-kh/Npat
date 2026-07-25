"""
Persisted game records.

Design note: live, fast-changing state (who's typing, current round timer,
which answers are locked right now) lives in Redis and is owned by
services/room_manager.py + services/game_manager.py. These tables are the
durable record written at meaningful checkpoints (room created, round
completed, game finished) so history/stats can survive process restarts
and be queried later - they are NOT read on every socket event.
"""
import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import String, DateTime, JSON, ForeignKey, Integer, Boolean, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.session import Base


class RoomStatus(str, Enum):
    LOBBY = "lobby"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    room_code: Mapped[str] = mapped_column(String(8), unique=True, nullable=False, index=True)
    host_player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id"), nullable=False)
    status: Mapped[RoomStatus] = mapped_column(SAEnum(RoomStatus), default=RoomStatus.LOBBY)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rounds: Mapped[list["Round"]] = relationship(back_populates="room", cascade="all, delete-orphan")


class Round(Base):
    __tablename__ = "rounds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    room_id: Mapped[str] = mapped_column(String(36), ForeignKey("rooms.id"), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    letter: Mapped[str] = mapped_column(String(1), nullable=False)

    # e.g. ["Name", "Animal", "Food", "Movie"]
    categories: Mapped[list] = mapped_column(JSON, nullable=False)

    locked_by_player_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    room: Mapped["Room"] = relationship(back_populates="rounds")
    answers: Mapped[list["Answer"]] = relationship(back_populates="round", cascade="all, delete-orphan")


class AnswerStatus(str, Enum):
    PENDING = "pending"          # not yet validated
    VALID = "valid"
    INVALID = "invalid"
    DUPLICATE = "duplicate"
    BLANK = "blank"


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    round_id: Mapped[str] = mapped_column(String(36), ForeignKey("rounds.id"), nullable=False)
    player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id"), nullable=False)

    category: Mapped[str] = mapped_column(String(30), nullable=False)
    text: Mapped[str] = mapped_column(String(60), nullable=False, default="")

    status: Mapped[AnswerStatus] = mapped_column(SAEnum(AnswerStatus), default=AnswerStatus.PENDING)
    points_awarded: Mapped[int] = mapped_column(Integer, default=0)

    # True if this answer was ever challenged, regardless of outcome -
    # used for the "Challenger" achievement and end-of-round stats.
    was_challenged: Mapped[bool] = mapped_column(Boolean, default=False)
    validated_via: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "dataset" | "groq" | None

    round: Mapped["Round"] = relationship(back_populates="answers")
