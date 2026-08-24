"""Least-privilege production ingestion entry point.

Schema migrations are an explicit deployment concern. Scheduled production ingestion
must never require database-owner DDL privileges just to collect a snapshot.
"""

from __future__ import annotations

import json
from typing import Any

from .api_client import FPLClient
from .model import ExpectedPointsModel
from .storage import Store


def run_once(database_url: str | None = None) -> dict[str, Any]:
    """Fetch, predict, and persist once without applying schema migrations."""
    client = FPLClient()
    snapshot = client.snapshot()
    predictions = ExpectedPointsModel().predict(snapshot)
    store = Store(database_url)
    if not store.is_postgres:
        raise RuntimeError("production_run requires a PostgreSQL production database")

    ingestion_id, inserted = store.save_snapshot(snapshot)
    # Persist official gameweek metadata (deadlines) so read paths can show
    # countdowns without any page-load call to the FPL API.
    store.save_season_events(
        snapshot.bootstrap.get("events") or [], snapshot.fetched_at.isoformat()
    )
    prediction_run_id = store.save_predictions(ingestion_id, snapshot, predictions)
    return {
        "status": "ok",
        "source_hash": snapshot.source_hash,
        "data_as_of": snapshot.fetched_at.isoformat(),
        "target_event": predictions[0].target_event,
        "model_version": predictions[0].model_version,
        "players": len(snapshot.bootstrap["elements"]),
        "teams": len(snapshot.bootstrap["teams"]),
        "fixtures": len(snapshot.fixtures),
        "ingestion_run_id": ingestion_id,
        "prediction_run_id": prediction_run_id,
        "new_source_snapshot": inserted,
    }


def main() -> None:
    print(json.dumps(run_once(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
