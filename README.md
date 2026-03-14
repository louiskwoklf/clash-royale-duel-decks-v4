# clash-royale-duel-decks-v4

Web app for building Clash Royale duel decks from ranked Path of Legends decks stored from recently ingested battle logs.

## Features
- Sync cards from the Clash Royale API
- Seed top Path of Legends players
- Expand the player pool from battle opponents
- Ingest battle logs into SQLite
- Query ranked decks with include and exclude filters
- Build 4-deck duel bundles with 32 unique cards from the top filtered ranked decks
- Browse duel deck results in the web UI or JSON API

Rankings are based on battle-log entries whose battle `type` is `pathoflegend`. If you previously ingested mixed-mode data, clear battle data and ingest again to rebuild with strict Path of Legends storage.

## Setup
1. Create a virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env`.
4. Add your Clash Royale API token to `.env`.
5. Start the server with `uvicorn app.main:app --reload`.

## Environment Variables
- `API_TOKEN`: Clash Royale API token. Keep this server-side only.
- `BASE_URL`: Clash Royale API base URL.
- `SQLITE_DB_PATH`: SQLite database path. One SQLite file contains multiple tables, so the default name is intentionally generic.
- `DUEL_DECK_POOL_SIZE`: How many top-ranked individual decks are considered when building duel deck bundles.
- Ranking, retry, and ingestion tuning values are also defined in `.env.example`.

## Run
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/`.

## Initial Ingestion
The app starts with an empty database. The easiest path is to open the homepage and use the admin buttons for:

- `Sync cards`
- `Seed players`
- `Expand player pool`
- `Ingest battles`

The page also shows current database stats and provides clear-data buttons for cards, players, battle data, or everything.

If you still want direct API calls, run these after the server is up:

```bash
curl -X POST http://127.0.0.1:8000/api/admin/sync-cards
curl -X POST http://127.0.0.1:8000/api/admin/seed-players
curl -X POST http://127.0.0.1:8000/api/admin/expand-player-pool
curl -X POST http://127.0.0.1:8000/api/admin/ingest-battles
```

After that, the homepage and `GET /api/duel-decks` should return stored results.

On startup, the app also upgrades older databases to preserve variant-aware deck card keys derived from stored battle JSON, such as `-ev1` and `-hero`, so existing battle data does not need to be wiped just to recover those identifiers.

## Main Routes
- `GET /`: HTML dashboard for building duel decks
- `GET /api/health`: health check
- `GET /api/decks`: ranked deck query
- `GET /api/duel-decks`: duel deck builder query from the top filtered ranked decks
- `GET /api/admin/stats`: database counts and recent timestamps
- `POST /api/admin/sync-cards`: refresh card catalog
- `POST /api/admin/seed-players`: seed Path of Legends players
- `POST /api/admin/expand-player-pool`: discover more players from opponents
- `POST /api/admin/ingest-battles`: ingest battle logs into SQLite
- `POST /api/admin/clear-cards`: clear card catalog
- `POST /api/admin/clear-players`: clear stored players
- `POST /api/admin/clear-battles`: clear battles, decks, and battle records
- `POST /api/admin/clear-all`: clear all stored data

## Notes
- Admin routes are unauthenticated and intended for local-only use.
- The Clash Royale API token must remain on the server and must not be exposed to the browser.
