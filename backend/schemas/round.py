from pydantic import BaseModel, Field


class NewRoundOut(BaseModel):
    round_number: int
    letter: str
    categories: list[str]
    letters_remaining: int


class AnswerSubmit(BaseModel):
    category: str
    text: str = Field(default="", max_length=60)


class SubmitAnswersRequest(BaseModel):
    player_id: str
    room_code: str
    answers: list[AnswerSubmit]


class PlayerDoneRequest(BaseModel):
    player_id: str
    room_code: str


class ChallengeRequest(BaseModel):
    room_code: str
    challenger_player_id: str
    target_player_id: str
    category: str


class RevealedAnswer(BaseModel):
    player_id: str
    username: str
    category: str
    text: str
    status: str  # pending | valid | invalid | duplicate | blank
    points_awarded: int
    was_challenged: bool = False


class RoundLockedOut(BaseModel):
    round_number: int
    locked_by_player_id: str
    answers: list[RevealedAnswer]


class ChallengeResultOut(BaseModel):
    round_number: int
    target_player_id: str
    category: str
    new_status: str
    validated_via: str  # "dataset" | "groq"
    points_awarded: int
