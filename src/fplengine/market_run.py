"""Lightweight scheduled market-intelligence ingestion.

Captures official observed market state (prices, ownership, transfer counters,
status/news) plus gameweek deadline metadata from bootstrap-static only. This
runner deliberately does NOT fetch fixtures, run the expected-points model or
touch historical research: it is cheap enough for a half-hourly schedule.

Storage is a sliding window (default 7 days) of compact per-poll snapshots that
the runner prunes itself, keeping Neon growth bounded at low tens of megabytes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .api_client import FPLClient
from .storage import Store


def market_source_hash(elements: list[dict[str, Any]]) -> str:
    """Hash the market-relevant projection of a bootstrap payload.

    Identity fields (photos, names) are excluded so cosmetic bootstrap churn does
    not grow history; identical market states dedupe to the same hash.
    """
    projection = [
        {
            "id": int(row["id"]),
            "now_cost": int(row["now_cost"]),
            "selected_by_percent": str(row.get("selected_by_percent") or ""),
            "transfers_in_event": int(row.get("transfers_in_event") or 0),
            "transfers_out_event": int(row.get("transfers_out_event") or 0),
            "status": str(row.get("status") or ""),
            "chance_of_playing_next_round": row.get("chance_of_playing_next_round"),
            "news": str(row.get("news") or ""),
        }
        for row in sorted(elements, key=lambda item: int(item["id"]))
    ]
    canonical = json.dumps(projection, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def run_once(database_url: str | None = None) -> dict[str, Any]:
    """Poll once without applying schema migrations (least-privilege friendly)."""
    client = FPLClient()
    bootstrap = client.bootstrap()
    elements = [row for row in bootstrap.get("elements", []) if row.get("now_cost") is not None]
    if not elements:
        raise RuntimeError("bootstrap payload contained no marketable players")
    store = Store(database_url)
    if not store.is_postgres:
        raise RuntimeError("market_run requires a PostgreSQL production database")

    captured_at = datetime.now(UTC).isoformat()
    events_saved = store.save_season_events(bootstrap.get("events") or [], captured_at)
    source_hash = market_source_hash(elements)
    poll_id, inserted = store.save_market_poll(elements, captured_at, source_hash)
    pruned = store.prune_market_history() if inserted else 0
    return {
        "status": "ok",
        "poll_id": poll_id,
        "inserted": inserted,
        "captured_at": captured_at,
        "players": len(elements),
        "season_events_upserted": events_saved,
        "pruned_polls": pruned,
        "duplicate_state": not inserted,
    }


def main() -> None:
    print(json.dumps(run_once(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
