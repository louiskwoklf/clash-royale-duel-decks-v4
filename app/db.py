from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Any

from app.config import settings


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS players (
    tag TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    trophies INTEGER,
    last_seen_at TEXT NOT NULL DEFAULT '',
    last_seeded_at TEXT NOT NULL DEFAULT '',
    last_expanded_at TEXT NOT NULL DEFAULT '',
    last_battlelog_at TEXT NOT NULL DEFAULT '',
    raw_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    max_level INTEGER,
    elixir_cost INTEGER,
    icon_url TEXT NOT NULL DEFAULT '',
    last_synced_at TEXT NOT NULL DEFAULT '',
    raw_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS battles (
    battle_key TEXT PRIMARY KEY,
    battle_time TEXT NOT NULL,
    game_mode TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL DEFAULT '',
    arena_id INTEGER,
    raw_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decks (
    deck_signature TEXT PRIMARY KEY,
    card_ids_json TEXT NOT NULL,
    card_keys_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deck_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battle_key TEXT NOT NULL,
    player_tag TEXT NOT NULL,
    opponent_tag TEXT NOT NULL DEFAULT '',
    deck_signature TEXT NOT NULL,
    win_value REAL NOT NULL,
    crowns_for INTEGER NOT NULL DEFAULT 0,
    crowns_against INTEGER NOT NULL DEFAULT 0,
    battle_time TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (battle_key, player_tag),
    FOREIGN KEY (battle_key) REFERENCES battles(battle_key) ON DELETE CASCADE,
    FOREIGN KEY (deck_signature) REFERENCES decks(deck_signature) ON DELETE CASCADE,
    FOREIGN KEY (player_tag) REFERENCES players(tag) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_players_last_seen ON players(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_players_last_battlelog ON players(last_battlelog_at);
CREATE INDEX IF NOT EXISTS idx_cards_slug ON cards(slug);
CREATE INDEX IF NOT EXISTS idx_deck_observations_time ON deck_observations(battle_time);
CREATE INDEX IF NOT EXISTS idx_deck_observations_signature ON deck_observations(deck_signature);
CREATE INDEX IF NOT EXISTS idx_deck_observations_player ON deck_observations(player_tag);
"""


def db_connect(path: str | None = None) -> sqlite3.Connection:
    db_path = Path(path or settings.sqlite_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with db_connect() as conn:
        conn.executescript(SCHEMA_SQL)
        _ensure_schema_upgrades(conn)
        _migrate_variant_decks(conn)
        conn.commit()


def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(str(row["name"]) == column for row in rows)


def _ensure_schema_upgrades(conn: sqlite3.Connection) -> None:
    if not _table_has_column(conn, "decks", "card_keys_json"):
        conn.execute("ALTER TABLE decks ADD COLUMN card_keys_json TEXT NOT NULL DEFAULT '[]'")
    if not _table_has_column(conn, "cards", "last_synced_at"):
        conn.execute("ALTER TABLE cards ADD COLUMN last_synced_at TEXT NOT NULL DEFAULT ''")


def _migrate_variant_decks(conn: sqlite3.Connection) -> None:
    missing_card_keys = conn.execute(
        """
        SELECT 1
        FROM decks
        WHERE card_keys_json = '[]'
        LIMIT 1
        """
    ).fetchone()

    legacy_variant_keys = conn.execute(
        """
        SELECT 1
        FROM decks
        WHERE deck_signature LIKE '%-hero%'
           OR deck_signature LIKE '%-ev%'
        LIMIT 1
        """
    ).fetchone()

    has_variant_payloads = conn.execute(
        """
        SELECT 1
        FROM battles
        WHERE raw_json LIKE '%"evolutionLevel"%'
        LIMIT 1
        """
    ).fetchone()

    needs_variant_rebuild = bool(has_variant_payloads) and not legacy_variant_keys

    if not missing_card_keys and not needs_variant_rebuild:
        return

    from app.services.ingest import migrate_deck_variants

    updated = migrate_deck_variants(conn)
    if updated > 0:
        cleanup_orphaned_records(conn)


def _database_file_paths(path: str | None = None) -> list[Path]:
    db_path = Path(path or settings.sqlite_db_path)
    return [
        db_path,
        Path(f"{db_path}-wal"),
    ]


def _changes_before(conn: sqlite3.Connection) -> int:
    return int(conn.total_changes)


def _changes_after(conn: sqlite3.Connection, before: int) -> int:
    return int(conn.total_changes) - before


def cleanup_orphaned_records(conn: sqlite3.Connection) -> int:
    before = _changes_before(conn)
    conn.execute(
        """
        DELETE FROM battles
        WHERE NOT EXISTS (
            SELECT 1 FROM deck_observations o
            WHERE o.battle_key = battles.battle_key
        )
        """
    )
    conn.execute(
        """
        DELETE FROM decks
        WHERE NOT EXISTS (
            SELECT 1 FROM deck_observations o
            WHERE o.deck_signature = decks.deck_signature
        )
        """
    )
    return _changes_after(conn, before)


def clear_cards(conn: sqlite3.Connection) -> int:
    before = _changes_before(conn)
    conn.execute("DELETE FROM cards")
    return _changes_after(conn, before)


def clear_players(conn: sqlite3.Connection) -> int:
    before = _changes_before(conn)
    conn.execute("DELETE FROM players")
    cleanup_orphaned_records(conn)
    return _changes_after(conn, before)


def clear_battles(conn: sqlite3.Connection) -> int:
    before = _changes_before(conn)
    conn.execute("DELETE FROM deck_observations")
    conn.execute("DELETE FROM battles")
    conn.execute("DELETE FROM decks")
    return _changes_after(conn, before)


def clear_all_data(conn: sqlite3.Connection) -> int:
    before = _changes_before(conn)
    conn.execute("DELETE FROM deck_observations")
    conn.execute("DELETE FROM battles")
    conn.execute("DELETE FROM decks")
    conn.execute("DELETE FROM players")
    conn.execute("DELETE FROM cards")
    return _changes_after(conn, before)


def reclaim_disk_space(conn: sqlite3.Connection) -> None:
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("VACUUM")


def get_record_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "players": int(conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]),
        "cards": int(conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]),
        "battles": int(conn.execute("SELECT COUNT(*) FROM battles").fetchone()[0]),
        "decks": int(conn.execute("SELECT COUNT(*) FROM decks").fetchone()[0]),
        "battle_records": int(conn.execute("SELECT COUNT(*) FROM deck_observations").fetchone()[0]),
    }


def get_db_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    counts = get_record_counts(conn)
    size_bytes = sum(path.stat().st_size for path in _database_file_paths() if path.exists())

    return {
        "db_size_bytes": int(size_bytes),
        "counts": counts,
        "last_player_pool_update": conn.execute("SELECT MAX(last_expanded_at) FROM players").fetchone()[0],
        "last_battle_ingest": conn.execute("SELECT MAX(last_battlelog_at) FROM players").fetchone()[0],
    }


@contextmanager
def get_conn():
    conn = db_connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
