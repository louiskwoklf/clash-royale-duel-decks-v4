from __future__ import annotations

from pydantic import BaseModel, Field


class DeckQuery(BaseModel):
    days: int = Field(default=3, ge=1)
    limit: int = Field(default=20, ge=1, le=100)
    include: str = ""
    exclude: str = ""


class DeckResponseItem(BaseModel):
    deck_signature: str
    cards: list[int]
    card_keys: list[str]
    card_names: list[str]
    card_image_urls: list[str]
    wins: float
    games: float
    unique_players: int
    confidence: float
    popularity: float
    stability: float
    final_score: float
    win_rate: float


class AdminActionResponse(BaseModel):
    ok: bool
    message: str


class DatabaseStatsResponse(BaseModel):
    db_size_bytes: int
    counts: dict[str, int]
    last_player_pool_update: str | None = None
    last_battle_ingest: str | None = None


class AdminProgressResponse(BaseModel):
    action: str
    label: str
    message: str
    unit: str
    status: str
    current: int
    total: int
    percent: float
    active: bool
    updated_at: str
