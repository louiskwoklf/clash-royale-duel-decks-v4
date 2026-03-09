from __future__ import annotations

from hashlib import sha1
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import time
from urllib.parse import quote, urlparse

import requests

from app.config import settings


CARD_IMAGE_CACHE_CONTROL = "public, max-age=31536000, immutable"
ALLOWED_IMAGE_HOST = "api-assets.clashroyale.com"
ALLOWED_IMAGE_PREFIXES = (
    "/cards/",
    "/cardheroes/",
    "/cardevolutions/",
)


class CardImageCacheError(RuntimeError):
    pass


def ensure_card_image_cache_dir() -> Path:
    cache_dir = Path(settings.card_image_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def cache_key_for_url(source_url: str) -> str:
    return sha1(source_url.encode("utf-8")).hexdigest()


def local_card_image_url(source_url: str) -> str:
    cache_key = cache_key_for_url(source_url)
    return f"/card-images/{cache_key}.png?src={quote(source_url, safe='')}"


def _validate_source_url(source_url: str) -> str:
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or parsed.netloc != ALLOWED_IMAGE_HOST:
        raise CardImageCacheError("Invalid card image host.")
    if not parsed.path.endswith(".png") or not parsed.path.startswith(ALLOWED_IMAGE_PREFIXES):
        raise CardImageCacheError("Invalid card image path.")
    return source_url


def _image_path(cache_key: str) -> Path:
    return ensure_card_image_cache_dir() / f"{cache_key}.png"


def _missing_marker_path(cache_key: str) -> Path:
    return ensure_card_image_cache_dir() / f"{cache_key}.missing"


def _missing_marker_fresh(marker_path: Path) -> bool:
    if not marker_path.exists():
        return False
    age_seconds = max(0.0, time() - marker_path.stat().st_mtime)
    return age_seconds < settings.card_image_missing_ttl_seconds


def get_or_cache_card_image(source_url: str) -> Path | None:
    validated_url = _validate_source_url(source_url)
    cache_key = cache_key_for_url(validated_url)
    image_path = _image_path(cache_key)
    missing_marker_path = _missing_marker_path(cache_key)

    if image_path.exists():
        return image_path
    if _missing_marker_fresh(missing_marker_path):
        return None
    if missing_marker_path.exists():
        missing_marker_path.unlink()

    try:
        response = requests.get(validated_url, timeout=settings.request_timeout_seconds)
    except requests.RequestException as exc:
        raise CardImageCacheError("Failed to fetch card image.") from exc

    if response.status_code == 404:
        missing_marker_path.write_text("404\n", encoding="utf-8")
        return None
    if not response.ok:
        raise CardImageCacheError(f"Failed to fetch card image: HTTP {response.status_code}.")
    if "image/png" not in response.headers.get("Content-Type", ""):
        raise CardImageCacheError("Unexpected card image content type.")

    with NamedTemporaryFile(dir=str(image_path.parent), delete=False) as tmp:
        tmp.write(response.content)
        temp_path = Path(tmp.name)

    temp_path.replace(image_path)
    return image_path
