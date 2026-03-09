from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.clash_api import ApiError, ClashApiClient
from app.config import settings
from app.db import clear_all_data, clear_battles, clear_cards, clear_players, get_conn, get_db_stats, reclaim_disk_space
from app.jobs import job_runner
from app.progress import progress_tracker
from app.schemas import AdminActionResponse, AdminProgressResponse, DatabaseStatsResponse, DeckResponseItem
from app.services.ingest import expand_player_pool, ingest_battles, seed_top_players, sync_cards_catalog
from app.services.ranking import load_card_image_url_map, query_best_decks, serialize_deck_metric
from app.utils import parse_csv_tokens


router = APIRouter()


def build_api_client() -> ClashApiClient:
    return ClashApiClient(settings.api_token, settings.base_url)


def ensure_no_active_job() -> None:
    if job_runner.is_active():
        raise HTTPException(status_code=409, detail="Another admin job is already running.")


@router.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/api/admin/stats", response_model=DatabaseStatsResponse)
def admin_stats():
    with get_conn() as conn:
        return get_db_stats(conn)


@router.get("/api/admin/progress", response_model=AdminProgressResponse)
def admin_progress():
    return progress_tracker.snapshot()


@router.get("/api/decks", response_model=list[DeckResponseItem])
def decks(
    days: int = Query(default=settings.best_decks_days_default, ge=1),
    limit: int = Query(default=settings.best_decks_limit_default, ge=1, le=100),
    include: str = "",
    exclude: str = "",
):
    with get_conn() as conn:
        items = query_best_decks(
            conn=conn,
            days=days,
            limit=limit,
            include_cards=parse_csv_tokens(include),
            exclude_cards=parse_csv_tokens(exclude),
        )
        image_map = load_card_image_url_map(conn)
        return [serialize_deck_metric(conn, item, image_map=image_map) for item in items]


@router.post("/api/admin/sync-cards", response_model=AdminActionResponse)
def sync_cards_route():
    ensure_no_active_job()
    progress_tracker.begin(
        action="sync-cards",
        label="Sync Cards",
        unit="cards",
        message="Fetching card catalog...",
    )

    def run() -> None:
        api = build_api_client()
        try:
            with get_conn() as conn:
                count = sync_cards_catalog(
                    conn,
                    api,
                    progress=lambda current, total, message: progress_tracker.update(
                        current=current,
                        total=total,
                        message=message,
                    ),
                )
        except ApiError as exc:
            progress_tracker.fail(message=str(exc))
            return
        except Exception as exc:
            progress_tracker.fail(message=str(exc))
            return
        progress_tracker.finish(message=f"Cards synced: {count}", current=count, total=count)

    if not job_runner.start(run):
        raise HTTPException(status_code=409, detail="Another admin job is already running.")
    return {"ok": True, "message": "Started syncing cards."}


@router.post("/api/admin/seed-players", response_model=AdminActionResponse)
def seed_players_route():
    ensure_no_active_job()
    progress_tracker.begin(
        action="seed-players",
        label="Seed Players",
        unit="players",
        message="Fetching leaderboard players...",
    )

    def run() -> None:
        api = build_api_client()
        try:
            with get_conn() as conn:
                count = seed_top_players(
                    conn,
                    api,
                    progress=lambda current, total, message: progress_tracker.update(
                        current=current,
                        total=total,
                        message=message,
                    ),
                )
        except ApiError as exc:
            progress_tracker.fail(message=str(exc))
            return
        except Exception as exc:
            progress_tracker.fail(message=str(exc))
            return
        progress_tracker.finish(message=f"Players seeded: {count}", current=count, total=count)

    if not job_runner.start(run):
        raise HTTPException(status_code=409, detail="Another admin job is already running.")
    return {"ok": True, "message": "Started seeding players."}


@router.post("/api/admin/expand-player-pool", response_model=AdminActionResponse)
def expand_player_pool_route():
    ensure_no_active_job()
    progress_tracker.begin(
        action="expand-player-pool",
        label="Expand Player Pool",
        unit="players",
        message="Scanning player battle logs...",
    )

    def run() -> None:
        api = build_api_client()
        try:
            with get_conn() as conn:
                count = expand_player_pool(
                    conn,
                    api,
                    progress=lambda current, total, message: progress_tracker.update(
                        current=current,
                        total=total,
                        message=message,
                    ),
                )
        except ApiError as exc:
            progress_tracker.fail(message=str(exc))
            return
        except Exception as exc:
            progress_tracker.fail(message=str(exc))
            return
        snapshot = progress_tracker.snapshot()
        progress_tracker.finish(
            message=f"Players discovered: {count}",
            current=int(snapshot["current"]),
            total=int(snapshot["current"]),
        )

    if not job_runner.start(run):
        raise HTTPException(status_code=409, detail="Another admin job is already running.")
    return {"ok": True, "message": "Started expanding player pool."}


@router.post("/api/admin/ingest-battles", response_model=AdminActionResponse)
def ingest_battles_route():
    ensure_no_active_job()
    progress_tracker.begin(
        action="ingest-battles",
        label="Ingest Battles",
        unit="players",
        message="Scanning player battle logs...",
    )

    def run() -> None:
        api = build_api_client()
        try:
            with get_conn() as conn:
                count = ingest_battles(
                    conn,
                    api,
                    progress=lambda current, total, message: progress_tracker.update(
                        current=current,
                        total=total,
                        message=message,
                    ),
                )
        except ApiError as exc:
            progress_tracker.fail(message=str(exc))
            return
        except Exception as exc:
            progress_tracker.fail(message=str(exc))
            return
        snapshot = progress_tracker.snapshot()
        progress_tracker.finish(
            message=f"Battle records ingested: {count}",
            current=int(snapshot["current"]),
            total=int(snapshot["total"]),
        )

    if not job_runner.start(run):
        raise HTTPException(status_code=409, detail="Another admin job is already running.")
    return {"ok": True, "message": "Started ingesting battles."}


@router.post("/api/admin/clear-cards", response_model=AdminActionResponse)
def clear_cards_route():
    progress_tracker.begin(action="clear-cards", label="Clear Cards", unit="steps", total=1, message="Clearing cards...")
    with get_conn() as conn:
        count = clear_cards(conn)
        reclaim_disk_space(conn)
    progress_tracker.finish(message=f"Cards cleared: {count}", current=1, total=1)
    return {"ok": True, "message": f"Cards cleared: {count}"}


@router.post("/api/admin/clear-players", response_model=AdminActionResponse)
def clear_players_route():
    progress_tracker.begin(action="clear-players", label="Clear Players", unit="steps", total=1, message="Clearing players...")
    with get_conn() as conn:
        count = clear_players(conn)
        reclaim_disk_space(conn)
    progress_tracker.finish(message=f"Players cleared: {count}", current=1, total=1)
    return {"ok": True, "message": f"Players cleared: {count}"}


@router.post("/api/admin/clear-battles", response_model=AdminActionResponse)
def clear_battles_route():
    progress_tracker.begin(action="clear-battles", label="Clear Battle Data", unit="steps", total=1, message="Clearing battle data...")
    with get_conn() as conn:
        count = clear_battles(conn)
        reclaim_disk_space(conn)
    progress_tracker.finish(message=f"Battle data cleared: {count}", current=1, total=1)
    return {"ok": True, "message": f"Battle data cleared: {count}"}


@router.post("/api/admin/clear-all", response_model=AdminActionResponse)
def clear_all_route():
    progress_tracker.begin(action="clear-all", label="Clear Everything", unit="steps", total=1, message="Clearing all stored data...")
    with get_conn() as conn:
        count = clear_all_data(conn)
        reclaim_disk_space(conn)
    progress_tracker.finish(message=f"All stored data cleared: {count}", current=1, total=1)
    return {"ok": True, "message": f"All stored data cleared: {count}"}
