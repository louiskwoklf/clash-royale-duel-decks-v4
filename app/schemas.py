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


class DuelDeckResponseItem(BaseModel):
    combo_key: str
    unique_card_count: int
    total_final_score: float
    total_games: float
    total_unique_players: int
    subdecks: list[DeckResponseItem]


class DuelDeckQueryResponse(BaseModel):
    source_pool_size: int
    source_deck_count: int
    source_decks: list[DeckResponseItem]
    duel_decks: list[DuelDeckResponseItem]


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
    stoppable: bool
    updated_at: str
