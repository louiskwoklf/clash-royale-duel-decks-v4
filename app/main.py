from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.card_image_cache import ensure_card_image_cache_dir
from app.db import init_db
from app.routers.api import router as api_router
from app.routers.web import router as web_router


app = FastAPI(title="Clash Royale Deck Forge")


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    ensure_card_image_cache_dir()


app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount(
    "/background-images",
    StaticFiles(directory="data/background-images", check_dir=False),
    name="background-images",
)
app.include_router(web_router)
app.include_router(api_router)
