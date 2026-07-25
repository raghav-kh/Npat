"""
Import every model here so Alembic's autogenerate can discover them via
Base.metadata, and so the rest of the app can do `from models import Player`.
"""
from database.session import Base
from models.player import Player
from models.game import Room, Round, Answer, RoomStatus, AnswerStatus
from models.results import RoomResult

__all__ = [
    "Base",
    "Player",
    "Room",
    "Round",
    "Answer",
    "RoomStatus",
    "AnswerStatus",
    "RoomResult",
]
