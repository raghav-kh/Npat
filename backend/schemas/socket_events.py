"""
Validation for the payloads of client -> server Socket.IO events.

Socket.IO itself doesn't validate payload shape, so every handler in
sockets/rooms.py parses incoming data through one of these before touching
Redis - this turns a malformed payload into a single clear `error` event
instead of a raw KeyError/AttributeError deep in room_manager.
"""
from pydantic import BaseModel, Field

from schemas.player import AvatarConfig


class CreateRoomPayload(BaseModel):
    player_id: str
    username: str = Field(min_length=2, max_length=20)
    avatar_config: AvatarConfig = Field(default_factory=AvatarConfig)


class JoinRoomPayload(BaseModel):
    room_code: str = Field(min_length=4, max_length=8)
    player_id: str
    username: str = Field(min_length=2, max_length=20)
    avatar_config: AvatarConfig = Field(default_factory=AvatarConfig)


class LeaveRoomPayload(BaseModel):
    room_code: str
    player_id: str
