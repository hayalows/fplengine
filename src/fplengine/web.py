"""Thin read-only website for the Gameweek Decision Cockpit.

The frontend renders engine payloads to HTML and contains no model logic. The
preferred production flow is official FPL API -> scheduled ingestion -> stored
observations + versioned predictions -> this read layer. When a persisted
prediction run exists it is served from the database; live recomputation is an
explicitly labelled fallback for local development.
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .api_client import FPLClient, Snapshot
from .cockpit import assemble_cockpit, build_cockpit, build_personal_sections
from .model import POSITION_NAMES, Prediction
from . import webui
from .market import build_market_view
from .storage import Store

TABS: tuple[tuple[str, str], ...] = tuple(webui.ROUTES)


def page(tab: str, payload: dict[str, Any]) -> str:
    """Render one full website page for the given route."""
    route = tab if tab in webui.ROUTE_TITLES else "home"
    return webui.render_page(route, payload)


def render_tab(tab: str, payload: dict[str, Any]) -> str:
    """Backward-compatible alias returning the same complete page."""
    return page(tab, payload)



def _attach_team_strength(payload: dict[str, Any]) -> None:
    report_path = Path("reports/team_strength_backtest.json")
    if report_path.exists():
        try:
            payload["team_strength"] = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass


def _persisted_deadline(store: Store, target_event: int) -> str | None:
    """Deadline for the gameweek from persisted season metadata (no FPL calls)."""
    try:
        events = store.season_events()
    except Exception:  # noqa: BLE001 - missing table must not break the read path
        return None
    row = next((item for item in events if item["id"] == target_event), None)
    return (row or {}).get("deadline_time")


def build_persisted_cockpit(
    store: Store,
) -> tuple[dict[str, Any], Snapshot, list[Prediction]] | None:
    """Assemble the cockpit purely from persisted observations and predictions.

    Returns (payload, snapshot, predictions), or None when no usable prediction run
    is stored so callers can fall back to the live API explicitly. This is the normal
    production data path: page views never fetch the full official FPL API and never
    recompute predictions.
    """
    run = store.latest_predictions()
    if not run or len(run["rows"]) < 15:
        return None
    observations = store.latest_observation_payload()
    if not observations:
        return None
    elements = {int(row["id"]): row for row in observations["elements"]}
    teams = {int(row["id"]): row for row in observations["teams"]}
    fixtures = store.stored_fixtures(run["target_event"])
    fixture_counts: dict[int, int] = {}
    for fixture in fixtures:
        if not fixture["finished"] and fixture["event"] == run["target_event"]:
            fixture_counts[fixture["team_h"]] = fixture_counts.get(fixture["team_h"], 0) + 1
            fixture_counts[fixture["team_a"]] = fixture_counts.get(fixture["team_a"], 0) + 1

    assumptions = run.get("assumptions") or {}
    confidence_map = assumptions.get("prediction_confidence", {})
    total_players = int(assumptions.get("league_total_players") or 0)
    predictions: list[Prediction] = []
    for row in sorted(run["rows"], key=lambda item: item["expected_points"], reverse=True):
        element = elements.get(int(row["player_id"]), {})
        position_id = int(element.get("element_type") or 1)
        price = int(element.get("now_cost") or 0) / 10.0
        ownership = float(element.get("selected_by_percent") or 0.0)
        net_transfers = int(element.get("transfers_in_event") or 0) - int(
            element.get("transfers_out_event") or 0
        )
        expected_points = float(row["expected_points"])
        selected_count = (
            max(1000.0, total_players * ownership / 100.0) if total_players else 1000.0
        )
        predictions.append(
            Prediction(
                player_id=int(row["player_id"]),
                player_code=int(element.get("code") or 0),
                player_name=str(row["name"]),
                team_id=int(row["team_id"]),
                team=str(teams.get(int(row["team_id"]), {}).get("short_name", "?")),
                position=POSITION_NAMES[position_id],
                price=price,
                ownership_percent=round(ownership, 2),
                target_event=run["target_event"],
                fixture_count=fixture_counts.get(int(row["team_id"]), 0),
                expected_minutes=float(row["expected_minutes"]),
                expected_points=expected_points,
                expected_goals=float(row.get("expected_goals") or 0.0),
                expected_assists=float(row.get("expected_assists") or 0.0),
                clean_sheet_probability=float(row.get("clean_sheet_probability") or 0.0),
                risk=float(row["risk"]),
                confidence=str(confidence_map.get(str(row["player_id"]), "low")),
                value_score=round(expected_points / price, 4) if price else 0.0,
                differential_score=round(
                    expected_points * math.sqrt(max(0.0, 1.0 - ownership / 100.0)), 4
                ),
                market_net_transfers=net_transfers,
                market_momentum_percent=round(100.0 * net_transfers / selected_count, 4),
                lower_bound=float(row["lower_bound"]),
                upper_bound=float(row["upper_bound"]),
                model_version=str(run["model_version"]),
                data_as_of=observations["fetched_at"],
                components=dict(row.get("components") or {}),
                provenance={
                    "observed": "persisted Neon observation snapshot",
                    "calculated": f"stored prediction run {run['run_id']}",
                    "prediction": f"expected FPL points for GW{run['target_event']}",
                },
            )
        )

    bootstrap = {
        "events": [
            {
                "id": run["target_event"],
                "is_current": False,
                "is_next": True,
                "finished": False,
                "deadline_time": _persisted_deadline(store, run["target_event"]),
            }
        ],
        "elements": observations["elements"],
        "teams": [
            {
                "id": row["id"],
                "code": row["id"],
                "name": row["name"],
                "short_name": row["short_name"],
            }
            for row in observations["teams"]
        ],
        "element_types": [{"id": value} for value in range(1, 5)],
        "total_players": total_players,
    }
    try:
        fetched_at = datetime.fromisoformat(observations["fetched_at"])
    except ValueError:
        fetched_at = datetime.now(UTC)
    snapshot = Snapshot.from_payloads(bootstrap, fixtures, fetched_at)
    payload = assemble_cockpit(snapshot, predictions, store=store, limit=30)
    payload["data_source"] = (
        f"persisted run {run['run_id']} ({run['generated_at']}) {run['model_version']}"
    )
    _attach_team_strength(payload)
    _attach_market_and_season(store, payload, predictions, elements, teams, fixtures)
    payload["_all_predictions"] = predictions
    return payload, snapshot, predictions


def _attach_market_and_season(
    store: Store,
    payload: dict[str, Any],
    predictions: list[Prediction],
    elements: dict[int, dict[str, Any]],
    teams: dict[int, dict[str, Any]],
    fixtures: list[dict[str, Any]],
) -> None:
    """Attach market intelligence, deadline metadata and freshness to a payload.

    Everything here is read from Neon; no FPL API calls and no model recomputation.
    """
    try:
        polls = store.market_polls(limit=200)
        states = store.market_states([row["id"] for row in polls])
        view = build_market_view(polls, states)
    except Exception as exc:  # noqa: BLE001 - market must degrade independently
        view = {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    if view.get("available"):
        fixtures_by_team: dict[int, list[dict[str, str]]] = {}
        for fixture in fixtures:
            for side in ("team_h", "team_a"):
                opponent = "team_a" if side == "team_h" else "team_h"
                fixtures_by_team.setdefault(int(fixture[side]), []).append(
                    {
                        "opponent": str(
                            teams.get(int(fixture[opponent]), {}).get("short_name", "?")
                        ),
                        "venue": "H" if side == "team_h" else "A",
                    }
                )
        enriched = []
        prediction_by_id = {row.player_id: row for row in predictions}
        element_by_id = {int(row["player_id"]): row for row in view["players"]}
        for player_id, row in sorted(element_by_id.items()):
            element = elements.get(player_id) or {}
            prediction = prediction_by_id.get(player_id)
            row = dict(row)
            row["name"] = element.get("web_name") or (
                prediction.player_name if prediction else f"#{player_id}"
            )
            team_id = int(element.get("team") or (prediction.team_id if prediction else 0))
            row["team"] = str(teams.get(team_id, {}).get("short_name", "?"))
            row["position"] = (
                POSITION_NAMES.get(int(element.get("element_type") or 0))
                or (prediction.position if prediction else "")
            )
            row["fixtures"] = fixtures_by_team.get(team_id, [])
            row["captured_at"] = view.get("captured_at")
            enriched.append(row)
        view["players"] = enriched
    payload["market"] = view
    try:
        events = store.season_events()
    except Exception:  # noqa: BLE001 - missing table must not break pages
        events = []
    target_event = int((payload.get("metadata") or {}).get("target_event") or 0)
    season_row = next(
        (row for row in events if row["id"] == target_event),
        next((row for row in events if row.get("is_next")), None),
    )
    payload["season"] = {
        "deadline_utc": (season_row or {}).get("deadline_time"),
        "event_name": (season_row or {}).get("name"),
    }
    as_of = (payload.get("metadata") or {}).get("data_as_of")
    minutes_old: int | None = None
    try:
        parsed = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
        minutes_old = max(0, int((datetime.now(UTC) - parsed).total_seconds() // 60))
    except ValueError:
        pass
    if minutes_old is None:
        level = None
    elif minutes_old < 480:
        level = "fresh"
    elif minutes_old < 2880:
        level = "stale"
    else:
        level = "old"
    payload["freshness"] = {
        "minutes_old": minutes_old,
        "level": level,
        "label": f"updated {_ago(minutes_old)}" if level else "age unknown",
    }


def _ago(minutes: int | None) -> str:
    from .webui import _ago_display

    return _ago_display(minutes)


def _all_player_records(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Full-squad records powering the players explorer (persisted data only)."""
    records: list[dict[str, Any]] = []
    market_rows = {
        row["player_id"]: row for row in (payload.get("market") or {}).get("players") or []
    }
    for row in payload.get("_all_predictions") or []:
        record = row.to_dict()
        market_row = market_rows.get(row.player_id, {})
        record["status"] = market_row.get("status")
        record["news"] = market_row.get("news")
        record["fixtures"] = market_row.get("fixtures") or []
        records.append(record)
    return records


class SiteCache:
    """Refreshes the assembled cockpit payload at most once per TTL.

    The normal path assembles everything from persisted Neon observations and
    predictions; per-entry endpoints are the only live calls and only refresh once
    per TTL. A full live recomputation happens solely as an explicit fallback when
    nothing usable is stored.
    """

    def __init__(
        self,
        store: Store | None,
        entry_id: int | None,
        ttl_seconds: int = 900,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.store = store
        self.entry_id = entry_id
        self.ttl_seconds = ttl_seconds
        self._client_factory = client_factory or FPLClient
        self._lock = threading.Lock()
        self._loaded_at = 0.0
        self.payload: dict[str, Any] | None = None
        self._client: Any | None = None

    def _client_for_entry(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def _refresh(self) -> dict[str, Any]:
        if self.store is not None:
            try:
                persisted = build_persisted_cockpit(self.store)
            except Exception:  # noqa: BLE001 - storage issues must fall back, not crash
                persisted = None
            if persisted is not None:
                payload, snapshot, predictions = persisted
                payload["all_players"] = _all_player_records(payload)
                payload.pop("_all_predictions", None)
                self._add_personal_sections(payload, snapshot, predictions)
                return payload
        payload = build_cockpit(
            self._client_for_entry(),
            self.store,
            entry_id=self.entry_id,
            limit=30,
        )
        payload["data_source"] = "live fallback"
        payload.setdefault("all_players", [])
        _attach_team_strength(payload)
        return payload

    def _add_personal_sections(
        self,
        payload: dict[str, Any],
        snapshot: Snapshot,
        predictions: list[Prediction],
    ) -> None:
        """Attach MY TEAM / NEXT GW from small per-entry endpoints onto stored data."""
        if self.entry_id is None:
            return
        try:
            personal = build_personal_sections(
                self._client_for_entry(),
                snapshot,
                predictions,
                self.entry_id,
            )
        except Exception as exc:  # noqa: BLE001 - manager context must not break briefs
            personal = {"my_team": {"error": f"{type(exc).__name__}: {exc}"}}
        payload["my_team"] = personal.get("my_team")
        payload["next_gw"] = personal.get("next_gw")
        payload["manager_state"] = personal.get("manager_state")
        if "error" in personal.get("my_team", {}):
            payload.setdefault("warnings", []).append(
                f"Personal team section failed: {personal['my_team']['error']}"
            )

    def get(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            if self.payload is None or now - self._loaded_at >= self.ttl_seconds:
                self.payload = self._refresh()
                self._loaded_at = now
            return self.payload


def make_web_handler(site_cache: SiteCache) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "fplengine-web/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/site/myteam")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if parsed.path == "/site" :
                tab = "myteam"
            elif parsed.path.startswith("/site/"):
                candidate = parsed.path.removeprefix("/site/")
                tab = candidate if any(candidate == key for key, _ in TABS) else "myteam"
            else:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-Type", "text/plain")
                body = b"not found"
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            payload = site_cache.get()
            body = page(tab, payload).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def serve_website(
    host: str = "127.0.0.1",
    port: int = 8001,
    database_url: str | None = None,
    entry_id: int | None = 7181076,
    initialize_schema: bool = False,
    ttl_seconds: int = 900,
) -> None:
    store: Store | None = Store(database_url)
    if not store.is_postgres or initialize_schema:
        store.initialize()
    cache = SiteCache(store=store, entry_id=entry_id, ttl_seconds=ttl_seconds)
    server = ThreadingHTTPServer((host, port), make_web_handler(cache))
    print(f"FPL Engine website listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
