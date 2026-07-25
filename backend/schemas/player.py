from pydantic import BaseModel, Field, field_validator


class AvatarConfig(BaseModel):
    """All fields optional with defaults so the client can send a partial
    config and still get a valid avatar."""
    hair: str = "short"
    eyes: str = "round"
    eyebrows: str = "normal"
    mouth: str = "smile"
    skin_tone: str = "#F1C27D"
    beard: str | None = None
    glasses: str | None = None
    hat: str | None = None
    background_color: str = "#7C3AED"


class PlayerCreate(BaseModel):
    username: str = Field(min_length=2, max_length=20)
    avatar_config: AvatarConfig = Field(default_factory=AvatarConfig)

    @field_validator("username")
    @classmethod
    def strip_and_validate_username(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Username cannot be blank")
        return v


class PlayerOut(BaseModel):
    id: str
    username: str
    avatar_config: dict

    model_config = {"from_attributes": True}
