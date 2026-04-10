from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
import json
import sqlite3
from typing import Any, Callable

from app.clash_api import ClashApiClient
from app.config import settings
from app.progress import progress_tracker
from app.utils import dedupe_preserve_order, encode_tag, json_dumps, mode_tokens, normalize_tag, slugify, to_iso_or_now, utc_now_iso, walk_dicts

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class Participant:
    tag: str
    name: str
    crowns: int
    cards: list[dict[str, Any]]
    raw: dict[str, Any]


def is_path_of_legends_battle(battle: dict[str, Any]) -> bool:
    return mode_tokens(str(battle.get("type", ""))) == {"pathoflegend"}


def upsert_player(conn: sqlite3.Connection, player: dict[str, Any], source: str = "") -> None:
    tag = normalize_tag(str(player.get("tag", "")))
    if not tag:
        return

    conn.execute(
        """
        INSERT INTO players (tag, name, source, trophies, last_seen_at, raw_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(tag) DO UPDATE SET
            name = excluded.name,
            source = CASE WHEN excluded.source <> '' THEN excluded.source ELSE players.source END,
            trophies = COALESCE(excluded.trophies, players.trophies),
            last_seen_at = excluded.last_seen_at,
            raw_json = excluded.raw_json
        """,
        (
            tag,
            str(player.get("name", "")),
            source,
            player.get("trophies") or player.get("expLevel"),
            utc_now_iso(),
            json_dumps(player),
        ),
    )


def sync_cards_catalog(
    conn: sqlite3.Connection,
    api: ClashApiClient,
    progress: ProgressCallback | None = None,
    *,
    resume: bool = False,
) -> int:
    payload = api.get("/cards")
    raw_items = payload.get("items", []) if isinstance(payload, dict) else []
    items: list[dict[str, Any]] = []
    for card in raw_items:
        if not isinstance(card, dict):
            continue
        card_id = card.get("id")
        name = str(card.get("name", "")).strip()
        if not isinstance(card_id, int) or not name:
            continue
        items.append(card)

    total = len(items)
    synced_ids: set[int] = set()
    if resume and items:
        card_ids = [int(card["id"]) for card in items]
        rows = conn.execute(
            f"SELECT id FROM cards WHERE last_synced_at <> '' AND id IN ({','.join('?' for _ in card_ids)})",
            card_ids,
        ).fetchall()
        synced_ids = {int(row["id"]) for row in rows}
    elif items:
        card_ids = [int(card["id"]) for card in items]
        conn.execute(
            f"UPDATE cards SET last_synced_at = '' WHERE id IN ({','.join('?' for _ in card_ids)})",
            card_ids,
        )
        conn.commit()

    count = len(synced_ids)
    if progress is not None:
        progress(count, total, "Fetched card catalog.")

    for card in items:
        progress_tracker.raise_if_stopped()
        card_id = int(card["id"])
        name = str(card["name"]).strip()
        if resume and card_id in synced_ids:
            continue
        icon_urls = card.get("iconUrls", {}) if isinstance(card.get("iconUrls"), dict) else {}
        conn.execute(
            """
            INSERT INTO cards (id, name, slug, max_level, elixir_cost, icon_url, last_synced_at, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                slug = excluded.slug,
                max_level = excluded.max_level,
                elixir_cost = excluded.elixir_cost,
                icon_url = excluded.icon_url,
                last_synced_at = excluded.last_synced_at,
                raw_json = excluded.raw_json
            """,
            (
                card_id,
                name,
                slugify(name),
                card.get("maxLevel"),
                card.get("elixirCost"),
                icon_urls.get("medium", ""),
                utc_now_iso(),
                json_dumps(card),
            ),
        )
        count += 1
        conn.commit()
        if progress is not None:
            progress(count, total, f"Syncing {count} of {total} cards.")

    return count


def load_card_token_map(conn: sqlite3.Connection) -> dict[str, int]:
    mapping: dict[str, int] = {}
    rows = conn.execute("SELECT id, name, slug FROM cards ORDER BY name").fetchall()
    for row in rows:
        card_id = int(row["id"])
        name = str(row["name"])
        tokens = {str(card_id), str(row["slug"]), slugify(name)}
        for token in mode_tokens(name):
            tokens.add(token)
        for token in tokens:
            mapping[token] = card_id
    return mapping


def card_slugs_for_ids(conn: sqlite3.Connection, card_ids: Iterable[int]) -> list[str]:
    ids = [int(card_id) for card_id in card_ids]
    if not ids:
        return []
    rows = conn.execute(
        f"SELECT id, slug FROM cards WHERE id IN ({','.join('?' for _ in ids)})",
        ids,
    ).fetchall()
    names_by_id = {int(row["id"]): str(row["slug"]) for row in rows}
    return [names_by_id.get(card_id, f"Card {card_id}") for card_id in ids]


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def card_key_for_payload(card: dict[str, Any]) -> str:
    card_id = card.get("id")
    base = slugify(str(card.get("name", "")).strip())
    if not base and isinstance(card_id, int):
        base = f"card-{card_id}"
    if not base:
        return ""
    evolution_level = _positive_int(card.get("evolutionLevel"))
    if evolution_level == 1:
        return f"{base}-ev1"
    if evolution_level is not None and evolution_level >= 2:
        return f"{base}-hero"
    return base


def battle_explicit_id(battle: dict[str, Any]) -> str:
    for key in ("battleId", "tag", "id"):
        value = battle.get(key)
        if value:
            return str(value)
    return ""


def build_battle_key(battle: dict[str, Any], player_tag: str) -> str:
    explicit = battle_explicit_id(battle)
    if explicit:
        return explicit
    basis = {
        "player_tag": normalize_tag(player_tag),
        "battle_time": battle.get("battleTime"),
        "type": battle.get("type"),
        "game_mode": battle.get("gameMode"),
        "team": battle.get("team"),
        "opponent": battle.get("opponent"),
    }
    return hashlib.sha1(json_dumps(basis).encode("utf-8")).hexdigest()


def parse_participants(battle: dict[str, Any]) -> list[Participant]:
    participants: list[Participant] = []
    for group_name in ("team", "opponent"):
        group = battle.get(group_name, [])
        if isinstance(group, dict):
            group = [group]
        if not isinstance(group, list):
            continue
        for item in group:
            if not isinstance(item, dict):
                continue
            participants.append(
                Participant(
                    tag=normalize_tag(str(item.get("tag", ""))),
                    name=str(item.get("name", "")),
                    crowns=int(item.get("crowns") or 0),
                    cards=item.get("cards", []) if isinstance(item.get("cards"), list) else [],
                    raw=item,
                )
            )
    return participants


def find_player_and_opponent(battle: dict[str, Any], player_tag: str) -> tuple[Participant | None, Participant | None]:
    normalized_player_tag = normalize_tag(player_tag)
    player: Participant | None = None
    opponent: Participant | None = None
    for participant in parse_participants(battle):
        if participant.tag == normalized_player_tag:
            player = participant
        elif opponent is None:
            opponent = participant
    return player, opponent


def extract_player_deck(player: Participant | None) -> list[int]:
    if player is None:
        return []
    deck_ids: list[int] = []
    for card in player.cards:
        card_id = card.get("id") if isinstance(card, dict) else None
        if isinstance(card_id, int):
            deck_ids.append(card_id)
        if len(deck_ids) == 8:
            break
    return deck_ids


def extract_player_deck_keys(player: Participant | None) -> list[str]:
    if player is None:
        return []
    deck_keys: list[str] = []
    for card in player.cards:
        if not isinstance(card, dict):
            continue
        card_key = card_key_for_payload(card)
        if card_key:
            deck_keys.append(card_key)
        if len(deck_keys) == 8:
            break
    return deck_keys


def deck_signature_for_card_keys(card_keys: Iterable[str]) -> str:
    unique_keys = sorted({str(card_key).strip() for card_key in card_keys if str(card_key).strip()})
    return "|".join(unique_keys)


def compute_win_value(player: Participant | None, opponent: Participant | None, battle: dict[str, Any]) -> float:
    if player and opponent:
        if player.crowns > opponent.crowns:
            return 1.0
        if player.crowns < opponent.crowns:
            return 0.0
        return 0.5

    result = str(battle.get("result", "")).lower()
    if "victory" in result or result == "win":
        return 1.0
    if "defeat" in result or result == "loss":
        return 0.0
    return 0.5


def migrate_deck_variants(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT
            o.id,
            o.player_tag,
            o.created_at,
            d.card_ids_json,
            b.raw_json
        FROM deck_observations o
        JOIN decks d ON d.deck_signature = o.deck_signature
        JOIN battles b ON b.battle_key = o.battle_key
        ORDER BY o.id ASC
        """
    ).fetchall()

    rebuilt_decks: dict[str, tuple[list[int], list[str], str]] = {}
    observation_updates: list[tuple[str, int]] = []

    for row in rows:
        try:
            battle = json.loads(str(row["raw_json"]) or "{}")
        except json.JSONDecodeError:
            battle = {}

        player, _ = find_player_and_opponent(battle, str(row["player_tag"]))
        card_ids = extract_player_deck(player)
        if len(card_ids) < 8:
            card_ids = [int(value) for value in json.loads(str(row["card_ids_json"]))]

        card_keys = extract_player_deck_keys(player)
        if len(card_keys) < len(card_ids):
            card_keys = card_slugs_for_ids(conn, card_ids)

        normalized_ids = sorted({int(card_id) for card_id in card_ids})
        normalized_keys = sorted({str(card_key) for card_key in card_keys if str(card_key)})
        if len(normalized_ids) != 8 or len(normalized_keys) != 8:
            continue

        deck_signature = deck_signature_for_card_keys(normalized_keys)
        created_at = str(row["created_at"])
        existing = rebuilt_decks.get(deck_signature)
        if existing is None or created_at < existing[2]:
            rebuilt_decks[deck_signature] = (normalized_ids, normalized_keys, created_at)
        observation_updates.append((deck_signature, int(row["id"])))

    for deck_signature, (card_ids, card_keys, created_at) in rebuilt_decks.items():
        conn.execute(
            """
            INSERT INTO decks (deck_signature, card_ids_json, card_keys_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(deck_signature) DO UPDATE SET
                card_ids_json = excluded.card_ids_json,
                card_keys_json = excluded.card_keys_json,
                created_at = MIN(decks.created_at, excluded.created_at)
            """,
            (
                deck_signature,
                json.dumps(card_ids),
                json.dumps(card_keys),
                created_at,
            ),
        )

    for deck_signature, observation_id in observation_updates:
        conn.execute(
            "UPDATE deck_observations SET deck_signature = ? WHERE id = ?",
            (deck_signature, observation_id),
        )

    return len(observation_updates)


def _looks_like_player_record(obj: dict[str, Any]) -> bool:
    tag = normalize_tag(str(obj.get("tag", "")))
    if not tag:
        return False
    keys = {"name", "trophies", "cards", "expLevel", "bestTrophies", "rank"}
    return any(key in obj for key in keys)


def _extract_tags_from_obj(obj: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    if _looks_like_player_record(obj):
        tag = normalize_tag(str(obj.get("tag", "")))
        if tag:
            tags.append(tag)
    return tags


def extract_player_tags(payload: Any) -> list[str]:
    tags: list[str] = []
    for obj in walk_dicts(payload):
        tags.extend(_extract_tags_from_obj(obj))
    return dedupe_preserve_order(tags)


def _parse_leaderboard_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get("items", [])
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _leaderboard_id(value: str) -> str:
    return slugify(value) or "leaderboard"


def _leaderboard_label(value: str) -> str:
    return value.strip("/") or "leaderboard"


def _fetch_tags_from_endpoint(api: ClashApiClient, endpoint: str) -> list[str]:
    payload = api.get(endpoint)
    items = _parse_leaderboard_entries(payload)
    if items:
        return dedupe_preserve_order(
            normalize_tag(str(item.get("tag", "")))
            for item in items
            if normalize_tag(str(item.get("tag", "")))
        )
    return extract_player_tags(payload)


def _fetch_tags_for_leaderboard_id(api: ClashApiClient, leaderboard_id: str) -> list[str]:
    endpoint = f"/locations/{leaderboard_id}/rankings/players"
    return _fetch_tags_from_endpoint(api, endpoint)


def _global_season_codes() -> list[str]:
    start = settings.pol_numeric_season_start
    end = settings.pol_numeric_season_min
    if start < end:
        start, end = end, start
    codes = ["global"]
    codes.extend(str(code) for code in range(start, end - 1, -1))
    return dedupe_preserve_order(codes)


def _try_path_of_legends_endpoints(api: ClashApiClient) -> list[str]:
    candidates = [
        "/locations/global/rankings/players",
        "/locations/global/pathoflegend/players",
        "/locations/global/rankings/pathoflegend/players",
    ]
    last_error: Exception | None = None
    had_successful_response = False
    for location_id in _global_season_codes():
        candidates.extend(
            [
                f"/locations/{location_id}/rankings/pathoflegend/players",
                f"/locations/{location_id}/pathoflegend/players",
            ]
        )

    for endpoint in dedupe_preserve_order(candidates):
        try:
            tags = _fetch_tags_from_endpoint(api, endpoint)
        except Exception as exc:
            last_error = exc
            continue
        had_successful_response = True
        if tags:
            return tags
    if not had_successful_response and last_error is not None:
        raise last_error
    return []


def fetch_top_path_of_legends_players_from_leaderboards(api: ClashApiClient) -> list[str]:
    return _try_path_of_legends_endpoints(api)


def fetch_player_battlelog(api: ClashApiClient, player_tag: str) -> list[dict[str, Any]]:
    payload = api.get(f"/players/{encode_tag(player_tag)}/battlelog")
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        items = payload.get("items", [])
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def seed_top_players(
    conn: sqlite3.Connection,
    api: ClashApiClient,
    progress: ProgressCallback | None = None,
    *,
    resume: bool = False,
) -> int:
    tags = fetch_top_path_of_legends_players_from_leaderboards(api)
    total = len(tags)
    seeded_tags: set[str] = set()
    if resume and tags:
        rows = conn.execute(
            f"SELECT tag FROM players WHERE last_seeded_at <> '' AND tag IN ({','.join('?' for _ in tags)})",
            tags,
        ).fetchall()
        seeded_tags = {str(row["tag"]) for row in rows}
    elif tags:
        conn.execute(
            f"UPDATE players SET last_seeded_at = '' WHERE tag IN ({','.join('?' for _ in tags)})",
            tags,
        )
        conn.commit()

    count = len(seeded_tags)
    if progress is not None:
        progress(count, total, "Fetched leaderboard players.")
    for tag in tags:
        progress_tracker.raise_if_stopped()
        if resume and tag in seeded_tags:
            continue
        upsert_player(conn, {"tag": tag}, source="path-of-legends")
        conn.execute(
            "UPDATE players SET last_seeded_at = ?, source = ? WHERE tag = ?",
            (utc_now_iso(), "path-of-legends", tag),
        )
        count += 1
        conn.commit()
        if progress is not None:
            progress(count, total, f"Seeding {count} of {total} players.")
    return count


def expand_player_pool(
    conn: sqlite3.Connection,
    api: ClashApiClient,
    progress: ProgressCallback | None = None,
) -> int:
    status_message = "Scanning battle logs for new players."
    target = settings.target_player_count
    starting_count = int(conn.execute("SELECT COUNT(*) AS count FROM players").fetchone()["count"])
    seeded_count = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM players
            WHERE last_seeded_at <> ''
            """
        ).fetchone()[0]
    )
    seeded_baseline = min(seeded_count, target)
    current = starting_count
    progress_total = max(0, target - seeded_baseline)
    if current >= target:
        if progress is not None:
            progress(progress_total, progress_total, "Player pool already at target.")
        return 0

    discovered = 0
    while current < target:
        progress_tracker.raise_if_stopped()
        if progress is not None:
            progress(
                max(0, current - seeded_baseline),
                progress_total,
                status_message,
            )
        rows = conn.execute(
            """
            SELECT tag
            FROM players
            WHERE last_expanded_at = ''
            ORDER BY last_seen_at DESC, tag ASC
            LIMIT 200
            """
        ).fetchall()
        if not rows:
            break

        for row in rows:
            progress_tracker.raise_if_stopped()
            player_tag = str(row["tag"])
            battlelog = fetch_player_battlelog(api, player_tag)
            if progress is not None:
                progress(
                    max(0, current - seeded_baseline),
                    progress_total,
                    status_message,
                )
            for battle in battlelog:
                progress_tracker.raise_if_stopped()
                if not is_path_of_legends_battle(battle):
                    continue
                for tag in extract_player_tags(battle):
                    progress_tracker.raise_if_stopped()
                    if conn.execute("SELECT 1 FROM players WHERE tag = ?", (tag,)).fetchone() is not None:
                        continue
                    if current >= target:
                        conn.commit()
                        return discovered
                    upsert_player(conn, {"tag": tag}, source="battlelog")
                    current += 1
                    discovered += 1
                    conn.commit()
                    if progress is not None:
                        progress(
                            max(0, current - seeded_baseline),
                            progress_total,
                            status_message,
                        )
                    if current >= target:
                        return discovered
            conn.execute("UPDATE players SET last_expanded_at = ? WHERE tag = ?", (utc_now_iso(), player_tag))
            conn.commit()
    return discovered


def ingest_player_battlelog(conn: sqlite3.Connection, api: ClashApiClient, player_tag: str) -> int:
    player_tag = normalize_tag(player_tag)
    if not player_tag:
        return 0

    now_iso = utc_now_iso()
    inserted = 0
    for battle in fetch_player_battlelog(api, player_tag):
        if not is_path_of_legends_battle(battle):
            continue
        player, opponent = find_player_and_opponent(battle, player_tag)
        deck_ids = extract_player_deck(player)
        deck_keys = extract_player_deck_keys(player)
        if len(deck_ids) < 8 or len(deck_keys) < 8:
            continue

        deck_signature = deck_signature_for_card_keys(deck_keys)
        battle_key = build_battle_key(battle, player_tag)
        battle_time = to_iso_or_now(battle.get("battleTime"))
        game_mode = battle.get("gameMode", {})
        game_mode_name = ""
        if isinstance(game_mode, dict):
            game_mode_name = str(game_mode.get("name", "") or game_mode.get("id", ""))
        elif game_mode:
            game_mode_name = str(game_mode)

        conn.execute(
            """
            INSERT INTO decks (deck_signature, card_ids_json, card_keys_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(deck_signature) DO UPDATE SET
                card_ids_json = excluded.card_ids_json,
                card_keys_json = excluded.card_keys_json
            """,
            (
                deck_signature,
                json.dumps(sorted(deck_ids)),
                json.dumps(sorted(deck_keys)),
                now_iso,
            ),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO battles (battle_key, battle_time, game_mode, event_type, arena_id, raw_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                battle_key,
                battle_time,
                game_mode_name,
                str(battle.get("type", "")),
                (battle.get("arena") or {}).get("id") if isinstance(battle.get("arena"), dict) else None,
                json_dumps(battle),
                now_iso,
            ),
        )

        result = conn.execute(
            """
            INSERT OR IGNORE INTO deck_observations (
                battle_key, player_tag, opponent_tag, deck_signature,
                win_value, crowns_for, crowns_against, battle_time, mode, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                battle_key,
                player_tag,
                opponent.tag if opponent else "",
                deck_signature,
                compute_win_value(player, opponent, battle),
                player.crowns if player else 0,
                opponent.crowns if opponent else 0,
                battle_time,
                game_mode_name,
                now_iso,
            ),
        )
        if result.rowcount > 0:
            inserted += 1

    conn.execute("UPDATE players SET last_battlelog_at = ? WHERE tag = ?", (now_iso, player_tag))
    return inserted


def ingest_battles(
    conn: sqlite3.Connection,
    api: ClashApiClient,
    progress: ProgressCallback | None = None,
    *,
    resume_current: int | None = None,
    resume_total: int | None = None,
) -> int:
    inserted = 0
    completed_count = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM players
            WHERE last_battlelog_at <> ''
            """
        ).fetchone()[0]
    )
    rows = conn.execute(
        """
        SELECT tag
        FROM players
        WHERE last_battlelog_at = ''
        ORDER BY last_seen_at DESC, tag ASC
        """
    ).fetchall()
    pending_tags = [str(row["tag"]) for row in rows]
    total = completed_count + len(pending_tags)
    if resume_total is not None:
        total = max(total, max(0, int(resume_total)))
    current = completed_count
    if resume_current is not None:
        current = max(current, max(0, int(resume_current)))

    if progress is not None:
        progress(current, total, "Scanning player battle logs...")

    for index, player_tag in enumerate(pending_tags, start=1):
        progress_tracker.raise_if_stopped()
        inserted += ingest_player_battlelog(conn, api, player_tag)
        conn.commit()
        if progress is not None:
            progress(current + index, total, player_tag)
    return inserted
