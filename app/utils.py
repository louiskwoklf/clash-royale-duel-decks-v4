from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import re
from typing import Any, Iterable
from urllib.parse import quote


def log(message: str) -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp} UTC] {message}")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_tag(tag: str) -> str:
    cleaned = (tag or "").strip().upper().replace("O", "0")
    if cleaned.startswith("#"):
        return cleaned
    if cleaned:
        return f"#{cleaned}"
    return ""


def encode_tag(tag: str) -> str:
    return quote(normalize_tag(tag), safe="")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug


def parse_battle_time(value: str | None) -> datetime | None:
    if not value:
        return None
    formats = ("%Y%m%dT%H%M%S.%fZ", "%Y%m%dT%H%M%S.000Z", "%Y%m%dT%H%M%SZ")
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def to_iso_or_now(value: str | datetime | None) -> str:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = parse_battle_time(value) if isinstance(value, str) else None
    if dt is None:
        return utc_now_iso()
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def wilson_lower_bound(wins: float, games: float, z: float) -> float:
    if games <= 0:
        return 0.0
    phat = wins / games
    z2 = z * z
    denom = 1.0 + z2 / games
    center = phat + z2 / (2.0 * games)
    margin = z * math.sqrt((phat * (1.0 - phat) + z2 / (4.0 * games)) / games)
    return clamp01((center - margin) / denom)


def normalized_log(value: float, baseline: float, lam: float = 0.5) -> float:
    if value <= 0:
        return 0.0
    baseline = max(1.0, baseline)
    ratio = math.log1p(value) / math.log1p(baseline)
    return clamp01(ratio**lam)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def mode_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.lower()) if token}


def dedupe_preserve_order(items: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def parse_csv_tokens(value: str) -> list[str]:
    if not value:
        return []
    tokens = [slugify(part.strip()) for part in value.split(",")]
    return [token for token in tokens if token]


def strip_card_variant_suffixes(value: str) -> str:
    token = slugify(value)
    while token:
        next_token = re.sub(r"-(?:ev\d+|hero)$", "", token)
        if next_token == token:
            break
        token = next_token
    return token


def iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=max(1, days))).replace(microsecond=0).isoformat()
