from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _load_dotenv(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = Path(path)
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


_DOTENV = _load_dotenv(".env")


def getenv_local(name: str, default: str) -> str:
    return os.getenv(name, _DOTENV.get(name, default))


@dataclass(frozen=True)
class Settings:
    api_token: str = getenv_local("API_TOKEN", "").strip()
    base_url: str = getenv_local("BASE_URL", "https://api.clashroyale.com/v1").rstrip("/")
    sqlite_db_path: str = getenv_local("SQLITE_DB_PATH", "data/app.sqlite3")
    card_image_cache_dir: str = getenv_local("CARD_IMAGE_CACHE_DIR", "data/card-images")
    card_image_missing_ttl_seconds: int = max(
        60,
        int(getenv_local("CARD_IMAGE_MISSING_TTL_SECONDS", "86400")),
    )

    target_player_count: int = int(getenv_local("TARGET_PLAYER_COUNT", "5000"))
    best_decks_days_default: int = int(getenv_local("BEST_DECKS_DAYS_DEFAULT", "3"))
    best_decks_limit_default: int = int(getenv_local("BEST_DECKS_LIMIT_DEFAULT", "20"))
    api_page_limit: int = max(1, int(getenv_local("API_PAGE_LIMIT", "100")))

    p0: float = float(getenv_local("P0", "20"))
    lam: float = float(getenv_local("LAMBDA", "0.5"))
    z: float = float(getenv_local("Z", "1.96"))

    request_timeout_seconds: float = float(getenv_local("REQUEST_TIMEOUT_SECONDS", "20"))
    max_retries: int = int(getenv_local("MAX_RETRIES", "5"))
    max_backoff_seconds: float = float(getenv_local("MAX_BACKOFF_SECONDS", "60"))
    request_initial_delay_seconds: float = float(getenv_local("REQUEST_INITIAL_DELAY_SECONDS", "1.0"))
    retry_min_delay_seconds: float = float(getenv_local("RETRY_MIN_DELAY_SECONDS", "1.0"))
    progress_poll_interval_ms: int = max(100, int(getenv_local("PROGRESS_POLL_INTERVAL_MS", "200")))
    progress_max_percent_per_second: float = max(5.0, float(getenv_local("PROGRESS_MAX_PERCENT_PER_SECOND", "35")))
    api_error_snippet_server: int = int(getenv_local("API_ERROR_SNIPPET_SERVER", "300"))
    api_error_snippet_generic: int = int(getenv_local("API_ERROR_SNIPPET_GENERIC", "500"))

    pol_numeric_season_start: int = int(getenv_local("POL_NUMERIC_SEASON_START", "200"))
    pol_numeric_season_min: int = int(getenv_local("POL_NUMERIC_SEASON_MIN", "90"))

    score_confidence_coef: float = float(getenv_local("SCORE_CONFIDENCE_COEF", "0.70"))
    score_popularity_coef: float = float(getenv_local("SCORE_POPULARITY_COEF", "0.15"))
    score_stability_coef: float = float(getenv_local("SCORE_STABILITY_COEF", "0.15"))


settings = Settings()
