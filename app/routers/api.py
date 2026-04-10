from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.clash_api import ApiError, ClashApiClient
from app.config import settings
from app.db import (
    clear_all_data,
    clear_battles,
    clear_cards,
    clear_players,
    get_conn,
    get_db_stats,
    get_record_counts,
    reclaim_disk_space,
)
from app.jobs import job_runner
from app.progress import StopRequested, progress_tracker
from app.schemas import (
    AdminActionResponse,
    AdminProgressResponse,
    DatabaseStatsResponse,
    DeckResponseItem,
    DuelDeckQueryResponse,
)
from app.services.ingest import expand_player_pool, ingest_battles, seed_top_players, sync_cards_catalog
from app.services.ranking import (
    build_duel_deck_metrics,
    load_card_image_url_map,
    query_best_decks,
    serialize_deck_metric,
    serialize_duel_deck_metric,
)
from app.utils import json_dumps, parse_csv_tokens


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


@router.post("/api/admin/stop", response_model=AdminActionResponse)
def stop_admin_job():
    if not job_runner.is_active():
        raise HTTPException(status_code=409, detail="No active admin job to stop.")
    if not progress_tracker.request_stop():
        raise HTTPException(status_code=409, detail="The active admin job cannot be stopped.")
    return {"ok": True, "message": "Stop requested."}


@router.get("/api/admin/progress/stream")
async def admin_progress_stream(request: Request):
    async def event_stream():
        last_event_id = request.headers.get("Last-Event-ID", "").strip()
        after_version = int(last_event_id) if last_event_id.isdigit() else -1

        while True:
            if await request.is_disconnected():
                break
            update = await asyncio.to_thread(progress_tracker.wait_for_update, after_version, 15.0)
            if update is None:
                yield ": keep-alive\n\n"
                continue
            after_version, snapshot = update
            yield (
                f"id: {after_version}\n"
                "event: progress\n"
                f"data: {json_dumps(snapshot)}\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def clear_action_totals(counts: dict[str, int]) -> dict[str, tuple[int, str]]:
    return {
        "clear-cards": (counts["cards"], "cards"),
        "clear-players": (counts["players"], "players"),
        "clear-battles": (counts["battle_records"] + counts["battles"] + counts["decks"], "records"),
        "clear-all": (sum(counts.values()), "records"),
    }


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


@router.get("/api/duel-decks", response_model=DuelDeckQueryResponse)
def duel_decks(
    days: int = Query(default=settings.best_decks_days_default, ge=1),
    include: str = "",
    exclude: str = "",
):
    with get_conn() as conn:
        source_decks = query_best_decks(
            conn=conn,
            days=days,
            limit=settings.duel_deck_pool_size,
            include_cards=parse_csv_tokens(include),
            exclude_cards=parse_csv_tokens(exclude),
        )
        duel_deck_items = build_duel_deck_metrics(source_decks)
        image_map = load_card_image_url_map(conn)
        return {
            "source_pool_size": settings.duel_deck_pool_size,
            "source_deck_count": len(source_decks),
            "source_decks": [serialize_deck_metric(conn, item, image_map=image_map) for item in source_decks],
            "duel_decks": [serialize_duel_deck_metric(conn, item, image_map=image_map) for item in duel_deck_items],
        }


@router.post("/api/admin/sync-cards", response_model=AdminActionResponse)
def sync_cards_route():
    ensure_no_active_job()
    previous_progress = progress_tracker.snapshot()
    resume = previous_progress.get("status") == "stopped" and previous_progress.get("action") == "sync-cards"
    progress_tracker.begin(
        action="sync-cards",
        label="Sync Cards",
        unit="cards",
        current=int(previous_progress["current"]) if resume else 0,
        total=int(previous_progress["total"]) if resume else 0,
        message="Fetching card catalog...",
        stoppable=True,
    )

    def run() -> None:
        api = build_api_client()
        try:
            with get_conn() as conn:
                count = sync_cards_catalog(
                    conn,
                    api,
                    resume=resume,
                    progress=lambda current, total, message: progress_tracker.update(
                        current=current,
                        total=total,
                        message=message,
                    ),
                )
        except StopRequested:
            snapshot = progress_tracker.snapshot()
            progress_tracker.stop(
                message=f"Sync stopped after {int(snapshot['current'])} cards.",
                current=int(snapshot["current"]),
                total=int(snapshot["total"]),
            )
            return
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
    previous_progress = progress_tracker.snapshot()
    resume = previous_progress.get("status") == "stopped" and previous_progress.get("action") == "seed-players"
    progress_tracker.begin(
        action="seed-players",
        label="Seed Players",
        unit="players",
        current=int(previous_progress["current"]) if resume else 0,
        total=int(previous_progress["total"]) if resume else 0,
        message="Fetching leaderboard players...",
        stoppable=True,
    )

    def run() -> None:
        api = build_api_client()
        try:
            with get_conn() as conn:
                count = seed_top_players(
                    conn,
                    api,
                    resume=resume,
                    progress=lambda current, total, message: progress_tracker.update(
                        current=current,
                        total=total,
                        message=message,
                    ),
                )
        except StopRequested:
            snapshot = progress_tracker.snapshot()
            progress_tracker.stop(
                message=f"Seeding stopped after {int(snapshot['current'])} players.",
                current=int(snapshot["current"]),
                total=int(snapshot["total"]),
            )
            return
        except ApiError as exc:
            progress_tracker.fail(message=str(exc))
            return
        except Exception as exc:
            progress_tracker.fail(message=str(exc))
            return
        if count <= 0:
            progress_tracker.fail(message="No players were seeded.")
            return
        progress_tracker.finish(message=f"Players seeded: {count}", current=count, total=count)

    if not job_runner.start(run):
        raise HTTPException(status_code=409, detail="Another admin job is already running.")
    return {"ok": True, "message": "Started seeding players."}


@router.post("/api/admin/expand-player-pool", response_model=AdminActionResponse)
def expand_player_pool_route():
    ensure_no_active_job()
    with get_conn() as conn:
        player_count = int(conn.execute("SELECT COUNT(*) AS count FROM players").fetchone()["count"])
        seeded_count = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM players
                WHERE last_seeded_at <> ''
                """
            ).fetchone()[0]
        )
    seeded_baseline = min(seeded_count, settings.target_player_count)
    progress_tracker.begin(
        action="expand-player-pool",
        label="Expand Player Pool",
        unit="players",
        current=max(0, min(player_count, settings.target_player_count) - seeded_baseline),
        total=max(0, settings.target_player_count - seeded_baseline),
        message="Scanning player battle logs...",
        stoppable=True,
    )

    def run() -> None:
        api = build_api_client()
        try:
            with get_conn() as conn:
                current_player_count = int(conn.execute("SELECT COUNT(*) AS count FROM players").fetchone()["count"])
                if current_player_count <= 0:
                    progress_tracker.fail(message="No players available to expand from.")
                    return
                count = expand_player_pool(
                    conn,
                    api,
                    progress=lambda current, total, message: progress_tracker.update(
                        current=current,
                        total=total,
                        message=message,
                    ),
                )
        except StopRequested:
            snapshot = progress_tracker.snapshot()
            progress_tracker.stop(
                message=f"Expansion stopped after {int(snapshot['current'])} players.",
                current=int(snapshot["current"]),
                total=int(snapshot["total"]),
            )
            return
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
    previous_progress = progress_tracker.snapshot()
    resume = previous_progress.get("status") == "stopped" and previous_progress.get("action") == "ingest-battles"
    with get_conn() as conn:
        player_count = int(conn.execute("SELECT COUNT(*) AS count FROM players").fetchone()["count"])
        completed_count = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM players
                WHERE last_battlelog_at <> ''
                """
            ).fetchone()[0]
        )
    progress_tracker.begin(
        action="ingest-battles",
        label="Ingest Battles",
        unit="players",
        current=max(completed_count, int(previous_progress["current"])) if resume else completed_count,
        total=max(player_count, int(previous_progress["total"])) if resume else player_count,
        message="Scanning player battle logs...",
        stoppable=True,
    )

    def run() -> None:
        api = build_api_client()
        try:
            with get_conn() as conn:
                player_count = int(conn.execute("SELECT COUNT(*) AS count FROM players").fetchone()["count"])
                if player_count <= 0:
                    progress_tracker.fail(message="No players available to ingest battle logs from.")
                    return
                count = ingest_battles(
                    conn,
                    api,
                    resume_current=int(previous_progress["current"]) if resume else None,
                    resume_total=int(previous_progress["total"]) if resume else None,
                    progress=lambda current, total, message: progress_tracker.update(
                        current=current,
                        total=total,
                        message=message,
                    ),
                )
        except StopRequested:
            snapshot = progress_tracker.snapshot()
            progress_tracker.stop(
                message=f"Battle ingest stopped after {int(snapshot['current'])} players.",
                current=int(snapshot["current"]),
                total=int(snapshot["total"]),
            )
            return
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
    with get_conn() as conn:
        counts = get_record_counts(conn)
        total, unit = clear_action_totals(counts)["clear-cards"]
        progress_tracker.begin(
            action="clear-cards",
            label="Clear Cards",
            unit=unit,
            total=total,
            message="Clearing cards...",
        )
        clear_cards(conn)
        reclaim_disk_space(conn)
    progress_tracker.finish(message=f"Cards cleared: {total}", current=total, total=total)
    return {"ok": True, "message": f"Cards cleared: {total}"}


@router.post("/api/admin/clear-players", response_model=AdminActionResponse)
def clear_players_route():
    with get_conn() as conn:
        counts = get_record_counts(conn)
        total, unit = clear_action_totals(counts)["clear-players"]
        progress_tracker.begin(
            action="clear-players",
            label="Clear Players",
            unit=unit,
            total=total,
            message="Clearing players...",
        )
        clear_players(conn)
        reclaim_disk_space(conn)
    progress_tracker.finish(message=f"Players cleared: {total}", current=total, total=total)
    return {"ok": True, "message": f"Players cleared: {total}"}


@router.post("/api/admin/clear-battles", response_model=AdminActionResponse)
def clear_battles_route():
    with get_conn() as conn:
        counts = get_record_counts(conn)
        total, unit = clear_action_totals(counts)["clear-battles"]
        progress_tracker.begin(
            action="clear-battles",
            label="Clear Battle Data",
            unit=unit,
            total=total,
            message="Clearing battle data...",
        )
        clear_battles(conn)
        reclaim_disk_space(conn)
    progress_tracker.finish(message=f"Battle data cleared: {total}", current=total, total=total)
    return {"ok": True, "message": f"Battle data cleared: {total}"}


@router.post("/api/admin/clear-all", response_model=AdminActionResponse)
def clear_all_route():
    with get_conn() as conn:
        counts = get_record_counts(conn)
        total, unit = clear_action_totals(counts)["clear-all"]
        progress_tracker.begin(
            action="clear-all",
            label="Clear Everything",
            unit=unit,
            total=total,
            message="Clearing all stored data...",
        )
        clear_all_data(conn)
        reclaim_disk_space(conn)
    progress_tracker.finish(message=f"All stored data cleared: {total}", current=total, total=total)
    return {"ok": True, "message": f"All stored data cleared: {total}"}
