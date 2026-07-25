"""
Player identity endpoints. No auth - a player is created once and the
client (localStorage) remembers the returned id for future visits.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from models import Player
from schemas.player import PlayerCreate, PlayerOut

router = APIRouter(prefix="/api/players", tags=["players"])


@router.post("", response_model=PlayerOut, status_code=201)
async def create_player(payload: PlayerCreate, db: AsyncSession = Depends(get_db)):
    player = Player(
        username=payload.username,
        avatar_config=payload.avatar_config.model_dump(),
    )
    db.add(player)
    await db.commit()
    await db.refresh(player)
    return player


@router.get("/{player_id}", response_model=PlayerOut)
async def get_player(player_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Player).where(Player.id == player_id))
    player = result.scalar_one_or_none()
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    return player
