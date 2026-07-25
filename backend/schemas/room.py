from pydantic import BaseModel, Field


class RoomCreate(BaseModel):
    host_player_id: str


class RoomOut(BaseModel):
    room_code: str
    host_player_id: str
    status: str


class JoinRoomRequest(BaseModel):
    room_code: str = Field(min_length=4, max_length=8)
    player_id: str


class PlayerPublicState(BaseModel):
    """What every client sees about every other player in a room."""
    player_id: str
    username: str
    avatar_config: dict
    is_host: bool = False
    status: str = "idle"  # idle | typing | done
    score: int = 0


class RoomStateOut(BaseModel):
    """Full snapshot of a room, sent on join / reconnect."""
    room_code: str
    status: str
    host_player_id: str
    players: list[PlayerPublicState]
    current_round_number: int | None = None
    letters_used: list[str] = []
    letters_remaining: int = 26
