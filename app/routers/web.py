from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.card_image_cache import CARD_IMAGE_CACHE_CONTROL, CardImageCacheError, cache_key_for_url, get_or_cache_card_image
from app.config import settings


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
STATIC_VERSION = str(int(max(
    Path("app/static/app.css").stat().st_mtime,
    Path("app/static/app.js").stat().st_mtime,
    Path("app/static/sw.js").stat().st_mtime,
)))


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    default_days = max(1, min(7, settings.best_decks_days_default))
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "static_version": STATIC_VERSION,
            "defaults": {
                "days": default_days,
                "duel_deck_pool_size": settings.duel_deck_pool_size,
            },
        },
    )


@router.get("/sw.js")
def service_worker():
    return FileResponse(
        "app/static/sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/card-images/{cache_key}.png")
def card_image(cache_key: str, src: str = Query(min_length=1)):
    if cache_key != cache_key_for_url(src):
        raise HTTPException(status_code=400, detail="Card image cache key mismatch.")
    try:
        image_path = get_or_cache_card_image(src)
    except CardImageCacheError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if image_path is None:
        raise HTTPException(status_code=404, detail="Card image not available.")
    return FileResponse(
        image_path,
        media_type="image/png",
        headers={"Cache-Control": CARD_IMAGE_CACHE_CONTROL},
    )
