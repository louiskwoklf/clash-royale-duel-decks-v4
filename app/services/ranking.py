from __future__ import annotations

from dataclasses import dataclass
import math
import json
import sqlite3

from app.card_image_cache import local_card_image_url
from app.config import settings
from app.services.ingest import card_slugs_for_ids, load_card_token_map
from app.utils import clamp01, iso_days_ago, normalized_log, strip_card_variant_suffixes, wilson_lower_bound


@dataclass
class DeckMetric:
    deck_signature: str
    cards: list[int]
    card_keys: list[str]
    wins: float
    games: float
    unique_players: int
    confidence: float
    popularity: float
    stability: float
    final_score: float
    win_rate: float


def resolve_card_filters(
    conn: sqlite3.Connection,
    include_cards: list[str],
    exclude_cards: list[str],
) -> tuple[set[int], set[int]]:
    mapping = load_card_token_map(conn)

    def resolve(tokens: list[str]) -> set[int]:
        resolved: set[int] = set()
        for token in tokens:
            if token.isdigit():
                resolved.add(int(token))
                continue
            if token in mapping:
                resolved.add(mapping[token])
                continue
            base_token = strip_card_variant_suffixes(token)
            if base_token in mapping:
                resolved.add(mapping[base_token])
        return resolved

    return resolve(include_cards), resolve(exclude_cards)


def compute_deck_rankings(
    conn: sqlite3.Connection,
    *,
    days: int,
    limit: int,
    include_ids: set[int],
    exclude_ids: set[int],
) -> list[DeckMetric]:
    since_iso = iso_days_ago(days)
    rows = conn.execute(
        """
        SELECT
            d.deck_signature,
            d.card_ids_json,
            d.card_keys_json,
            o.win_value,
            o.battle_time,
            o.player_tag
        FROM deck_observations o
        JOIN decks d ON d.deck_signature = o.deck_signature
        JOIN battles b ON b.battle_key = o.battle_key
        WHERE o.battle_time >= ?
          AND LOWER(b.event_type) = 'pathoflegend'
        """,
        (since_iso,),
    ).fetchall()

    buckets: dict[str, dict[str, object]] = {}
    for row in rows:
        cards = [int(value) for value in json.loads(str(row["card_ids_json"]))]
        card_keys = [str(value) for value in json.loads(str(row["card_keys_json"] or "[]"))]
        if not card_keys:
            card_keys = card_slugs_for_ids(conn, cards)
        card_set = set(cards)
        if include_ids and not include_ids.issubset(card_set):
            continue
        if exclude_ids and exclude_ids.intersection(card_set):
            continue

        signature = str(row["deck_signature"])
        bucket = buckets.setdefault(
            signature,
            {
                "cards": cards,
                "card_keys": card_keys,
                "wins": 0.0,
                "games": 0.0,
                "players": set(),
                "daily": {},
            },
        )
        bucket["wins"] = float(bucket["wins"]) + float(row["win_value"])
        bucket["games"] = float(bucket["games"]) + 1.0
        cast_players = bucket["players"]
        if isinstance(cast_players, set):
            cast_players.add(str(row["player_tag"]))
        cast_daily = bucket["daily"]
        if isinstance(cast_daily, dict):
            day = str(row["battle_time"])[:10]
            daily_wins, daily_games = cast_daily.get(day, (0.0, 0.0))
            cast_daily[day] = (daily_wins + float(row["win_value"]), daily_games + 1.0)

    metrics: list[DeckMetric] = []
    max_unique_players = max(
        (
            len(bucket["players"])
            for bucket in buckets.values()
            if isinstance(bucket["players"], set)
        ),
        default=0,
    )
    for signature, bucket in buckets.items():
        games = float(bucket["games"])
        wins = float(bucket["wins"])
        players = bucket["players"]
        unique_players = len(players) if isinstance(players, set) else 0
        win_rate = (wins / games) if games else 0.0
        player_factor = min(1.0, unique_players / settings.p0) if settings.p0 > 0 else 1.0
        effective_games = games * player_factor
        confidence = wilson_lower_bound(wins=win_rate * effective_games, games=effective_games, z=settings.z)
        popularity = normalized_log(unique_players, max_unique_players, 1.0)

        daily_rates: list[float] = []
        cast_daily = bucket["daily"]
        if isinstance(cast_daily, dict):
            for daily_wins, daily_games in cast_daily.values():
                if daily_games > 0:
                    daily_rates.append(daily_wins / daily_games)
        if daily_rates:
            mean_daily = sum(daily_rates) / len(daily_rates)
            if len(daily_rates) > 1:
                variance = sum((value - mean_daily) ** 2 for value in daily_rates) / len(daily_rates)
                stddev = math.sqrt(variance)
            else:
                stddev = 0.0
            stability = clamp01(mean_daily - settings.lam * stddev)
        else:
            stability = 0.0

        final_score = (
            settings.score_confidence_coef * confidence
            + settings.score_popularity_coef * popularity
            + settings.score_stability_coef * stability
        )
        metrics.append(
            DeckMetric(
                deck_signature=signature,
                cards=list(bucket["cards"]),
                card_keys=list(bucket["card_keys"]),
                wins=wins,
                games=games,
                unique_players=unique_players,
                confidence=confidence,
                popularity=popularity,
                stability=stability,
                final_score=final_score,
                win_rate=win_rate,
            )
        )

    metrics.sort(key=lambda item: (item.final_score, item.games, item.unique_players), reverse=True)
    return metrics[:limit]


def query_best_decks(
    conn: sqlite3.Connection,
    *,
    days: int,
    limit: int,
    include_cards: list[str],
    exclude_cards: list[str],
) -> list[DeckMetric]:
    include_ids, exclude_ids = resolve_card_filters(conn, include_cards, exclude_cards)
    return compute_deck_rankings(
        conn,
        days=max(1, days),
        limit=max(1, min(limit, 100)),
        include_ids=include_ids,
        exclude_ids=exclude_ids,
    )


def load_card_image_url_map(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    rows = conn.execute("SELECT slug, icon_url, raw_json FROM cards").fetchall()
    mapping: dict[str, dict[str, str]] = {}
    for row in rows:
        slug = str(row["slug"] or "").strip()
        if not slug:
            continue
        try:
            raw = json.loads(str(row["raw_json"] or "{}"))
        except json.JSONDecodeError:
            raw = {}
        icon_urls = raw.get("iconUrls", {}) if isinstance(raw, dict) and isinstance(raw.get("iconUrls"), dict) else {}
        mapping[slug] = {
            "medium": str(icon_urls.get("medium") or row["icon_url"] or "").strip(),
            "hero": str(icon_urls.get("heroMedium") or "").strip(),
            "evolution": str(icon_urls.get("evolutionMedium") or "").strip(),
        }
    return mapping


def resolve_card_image_url(card_key: str, image_map: dict[str, dict[str, str]]) -> str:
    base_key = strip_card_variant_suffixes(card_key)
    variants = image_map.get(base_key, {})
    if not variants:
        return ""
    if card_key.endswith("-hero") and variants.get("hero"):
        return local_card_image_url(str(variants["hero"]))
    if "-ev" in card_key and variants.get("evolution"):
        return local_card_image_url(str(variants["evolution"]))
    medium_url = str(variants.get("medium", ""))
    return local_card_image_url(medium_url) if medium_url else ""


def serialize_deck_metric(
    conn: sqlite3.Connection,
    deck: DeckMetric,
    image_map: dict[str, dict[str, str]] | None = None,
) -> dict:
    resolved_image_map = image_map if image_map is not None else load_card_image_url_map(conn)
    return {
        "deck_signature": deck.deck_signature,
        "cards": deck.cards,
        "card_keys": deck.card_keys,
        "card_names": deck.card_keys,
        "card_image_urls": [resolve_card_image_url(card_key, resolved_image_map) for card_key in deck.card_keys],
        "wins": deck.wins,
        "games": deck.games,
        "unique_players": deck.unique_players,
        "confidence": deck.confidence,
        "popularity": deck.popularity,
        "stability": deck.stability,
        "final_score": deck.final_score,
        "win_rate": deck.win_rate,
    }
