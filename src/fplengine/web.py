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
from .storage import Store

TABS = (
    ("myteam", "My Team"),
    ("picks", "Top Picks"),
    ("captain", "Captain"),
    ("transfers", "Transfers"),
    ("players", "Players"),
    ("fixtures", "Fixtures"),
    ("market", "Market"),
    ("changes", "What Changed"),
    ("model", "Model / Why"),
    ("premier", "Premier League"),
)

_STYLE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>FPL Engine</title><style>
body{font-family:system-ui,sans-serif;margin:0;background:#101418;color:#e8eaed}
nav{display:flex;flex-wrap:wrap;gap:.25rem;padding:.5rem;background:#171c22}
nav a{padding:.45rem .7rem;border-radius:6px;color:#cfd6dd;text-decoration:none;font-size:.9rem}
nav a.active,nav a:hover{background:#2a3440;color:#fff}
main{max-width:60rem;margin:0 auto;padding:1rem}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th,td{text-align:left;padding:.35rem .45rem;border-bottom:1px solid #232b33;white-space:nowrap}
tr:nth-child(even){background:#141a20}
.tag{display:inline-block;padding:.1rem .4rem;border-radius:4px;font-size:.72rem;
background:#31404f;margin-right:.3rem}
.warn{color:#ffcc66}.ok{color:#7bd88f}.bad{color:#ff8080}
h2{margin:1rem 0 .5rem;font-size:1.05rem}h1{font-size:1.2rem}
.src{color:#8b98a5;font-size:.78rem}</style></head><body>"""


def _table(headers: list[str], rows: list[list[str]], classes: list[str] | None = None) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = []
    for row in rows:
        cells = []
        for index, value in enumerate(row):
            css = f' class="{classes[index]}"' if classes and classes[index] else ""
            cells.append(f"<td{css}>{value}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _fixture_label(row: dict[str, Any]) -> str:
    return "/".join(f"{item['venue']}{escape(str(item['opponent']))}" for item in row.get("fixture", [])) or "-"


def _availability(row: dict[str, Any]) -> str:
    status = row.get("availability_status", "a")
    if status == "a":
        return '<span class="ok">available</span>'
    news = escape(str(row.get("availability_news", "")))[:40]
    return f'<span class="bad">{escape(status)}</span> {news}'


def render_tab(tab: str, payload: dict[str, Any]) -> str:
    meta = payload["metadata"]
    parts = [
        "<main>",
        "<h1>"
        f"GW{meta['target_event']} &middot; {escape(meta['model_version'])}"
        f"</h1><div class=src>as of {escape(meta['data_as_of'])} &middot; "
        f"deadline {escape(meta.get('deadline_utc') or '-')} &middot; "
        f"source {escape(payload.get('data_source', 'live'))}</div>",
    ]
    for warning in payload["warnings"]:
        parts.append(f'<div class="warn">{escape(warning)}</div>')

    if tab == "myteam":
        team = payload.get("my_team") or {}
        if "error" in team:
            parts.append(f"<h2>My Team</h2><div class=warn>{escape(team['error'])}</div>")
        else:
            rows = [
                [
                    str(row["position_slot"]),
                    f"{escape(str(row['name']))}{' (C)' if row['is_captain'] else ' (V)' if row['is_vice_captain'] else ''}",
                    _fixture_label(row),
                    f"{row.get('expected_points', 0):.1f}",
                    f"{row.get('expected_minutes', 0):.0f}",
                    f"{row.get('risk', 0):.2f}",
                    f"&pound;{row.get('price', 0):.1f}",
                    _availability(row),
                ]
                for row in team.get("players", [])
            ]
            parts.append("<h2>My Team</h2>")
            parts.append(_table(
                ["#", "Player", "Fixture", "xP", "xMins", "Risk", "Price", "Availability"],
                rows,
                classes=[None, None, None, None, None, None, None, None],
            ))
            state = payload.get("manager_state", {})
            if state:
                chips = "".join(
                    f"<span class=tag>{escape(name)}: {escape(str(state[name]['classification']))}</span>"
                    for name in state
                )
                parts.append(f"<p>{chips}</p>")
    elif tab == "picks":
        rows = [
            [
                str(row["rank"]),
                escape(row["player_name"]),
                row["team"],
                row["position"],
                f"&pound;{row['price']:.1f}",
                f"{row['expected_minutes']:.0f}",
                f"<b>{row['expected_points']:.2f}</b>",
                f"{row['risk']:.2f}",
                f"{row['ownership_percent']:.1f}%",
                escape(", ".join(f"{k} {v:+.1f}" for k, v in row["why_top_components"].items())),
            ]
            for row in payload["rankings"]
        ]
        parts.append("<h2>Top picks</h2>")
        parts.append(_table(
            ["#", "Player", "Team", "Pos", "Price", "xMins", "xP", "Risk", "Own%", "Why"],
            rows,
        ))
    elif tab == "captain":
        rows = [
            [
                escape(row["name"]),
                f"{row['expected_points']:.2f}",
                f"{row['ceiling_upper_bound']:.1f}",
                f"{row['risk']:.2f}",
                f"{row['ownership_percent']:.1f}%",
            ]
            for row in payload["captains"]
        ]
        parts.append("<h2>Captain candidates (ceiling)</h2>")
        parts.append(_table(["Player", "xP", "Ceiling", "Risk", "Own%"], rows))
    elif tab == "transfers":
        next_gw = payload.get("next_gw") or {}
        benchmark = payload.get("benchmark_squad") or {}
        if benchmark.get("lineups"):
            lineup = benchmark["lineups"][0]
            parts.append(
                f"<h2>Benchmark XI</h2><p>captain <b>{escape(lineup['captain']['name'])}</b>, "
                f"projected {lineup['projected_points']}, cost {benchmark.get('squad_cost')}</p>"
            )
        if "recommendation" in next_gw:
            rec = next_gw["recommendation"]
            plan = rec["recommended_plan"]
            label = rec["state_label"]
            colour = "ok" if rec["action"] == "ROLL" or label == "VERIFIED_INPUTS" else "warn"
            parts.append(
                f"<h2>Roll vs transfers</h2>"
                + _table(
                    ["Plan", "Transfers", "Hits", "Projected", "Gain vs roll"],
                    [
                        [
                            "ROLL" + (" *" if rec["action"] == "ROLL" else ""),
                            "0",
                            "0",
                            f"{next_gw['roll_plan']['projected_points']:.1f}",
                            "-",
                        ],
                        [
                            "ONE" + (" *" if rec["action"] == "TRANSFER (one)" else ""),
                            escape(", ".join(next_gw["best_single_transfer"]["transfers_in"]) or "-")
                            + " / "
                            + escape(", ".join(next_gw["best_single_transfer"]["transfers_out"]) or "-"),
                            str(next_gw["best_single_transfer"]["hit_cost"]),
                            f"{next_gw['best_single_transfer']['projected_points']:.1f}",
                            f"<b>{rec['gain_single_over_roll']:+.2f}</b>",
                        ],
                        [
                            "TWO" + (" *" if rec["action"] == "TRANSFER (two)" else ""),
                            escape(", ".join(next_gw["best_two_transfer"]["transfers_in"]) or "-")
                            + " / "
                            + escape(", ".join(next_gw["best_two_transfer"]["transfers_out"]) or "-"),
                            str(next_gw["best_two_transfer"]["hit_cost"]),
                            f"{next_gw['best_two_transfer']['projected_points']:.1f}",
                            f"<b>{rec['gain_double_over_roll']:+.2f}</b>",
                        ],
                    ],
                    classes=[None, None, None, None, None],
                )
            )
            parts.append(
                f"<h2>Transfer plan</h2><p class={colour}><b>{escape(rec['action'])}</b> "
                f"[{escape(label)}] - {escape(rec['reason'])}</p>"
                f"<p>IN {escape(', '.join(plan['transfers_in']) or '-')}; "
                f"OUT {escape(', '.join(plan['transfers_out']) or '-')}; "
                f"hits {plan['hit_cost']}; projected {plan['projected_points']}; "
                f"captain {escape(plan['captain'] or '')}</p>"
                f"<p class=src>bench order: {escape(', '.join(plan['bench_order']))}</p>"
            )
        elif "skipped" in payload.get("your_transfers", {}):
            parts.append(
                "<h2>Transfer plan</h2><p>Provide squad/bank state via CLI flags for a personal plan.</p>"
            )
    elif tab == "players":
        rows = [
            [
                str(index + 1),
                escape(row["player_name"]),
                row["team"],
                row["position"],
                f"{row['expected_minutes']:.0f}",
                f"{row['expected_points']:.2f}",
                f"[{row['lower_bound']:.1f}, {row['upper_bound']:.1f}]",
            ]
            for index, row in enumerate(payload.get("rankings", []))
        ]
        parts.append("<h2>Players (top of stored ranking)</h2>")
        parts.append(_table(["#", "Player", "Team", "Pos", "xMins", "xP", "Range"], rows))
    elif tab == "fixtures":
        rows = []
        for fixture in payload["fixtures"]:
            if fixture.get("note"):
                rows.append(["blank", ", ".join(escape(t) for t in fixture["teams"]), "", ""])
                continue
            score = f"{fixture['home_score']}-{fixture['away_score']}" if fixture["finished"] else ""
            rows.append([
                escape(fixture["home"]), escape(fixture["away"]), score,
                "FT" if fixture["finished"] else "upcoming",
            ])
        parts.append("<h2>Fixtures</h2>")
        parts.append(_table(["Home", "Away", "Score", "State"], rows))
    elif tab == "market":
        movers = payload["market_movers"]
        bought = "".join(
            f"<li>{escape(r['name'])} (+{r['net_transfers']}) xP {r['expected_points']}</li>"
            for r in movers["most_bought"]
        )
        sold = "".join(
            f"<li>{escape(r['name'])} ({r['net_transfers']}) xP {r['expected_points']}</li>"
            for r in movers["most_sold"]
        )
        parts.append(f"<h2>Most bought</h2><ul>{bought}</ul><h2>Most sold</h2><ul>{sold}</ul>")
    elif tab == "changes":
        changes = payload.get("changes_since_previous_snapshot", {})
        if changes.get("available"):
            rows = [
                [escape(row["name"]), f"+{row['price_change']:.1f}" if row["price_change"] > 0 else f"{row['price_change']:.1f}", f"{row['ownership_change_pp']:+.1f}pp", escape(row["news"][:50])]
                for row in changes["price_moves"] + changes["availability_or_news_changes"]
            ][:20]
            parts.append(
                f"<h2>What changed since {escape(changes['previous_captured_at'])}</h2>"
            )
            parts.append(_table(["Player", "&Delta;Price", "&Delta;Own%", "News"], rows) if rows else "<p>No material movement.</p>")
        else:
            parts.append(
                f"<h2>What changed</h2><p>{escape(changes.get('reason', 'unavailable'))}</p>"
            )
    elif tab == "model":
        provenance = meta.get("classification", {})
        items = "".join(
            f"<li><b>{escape(key.title())}</b>: {escape(value)}</li>" for key, value in provenance.items()
        )
        notes = "".join(f"<li>{escape(note)}</li>" for note in payload.get("uncertainty_notes", []))
        parts.append(
            f"<h2>Model</h2><p>version {escape(meta['model_version'])}, {meta['player_count']} players</p>"
            f"<h3>Provenance</h3><ul>{items}</ul><h3>Known limitations</h3><ul>{notes}</ul>"
        )
    elif tab == "premier":
        report = payload.get("team_strength")
        if not report:
            parts.append(
                "<h2>Premier League model</h2><p>No fitted report found on this server yet.</p>"
            )
        else:
            summary = report.get("summary", {})
            ratings_rows = [
                [escape(team), f"{value:+.3f}"]
                for team, value in report.get("final_fit_top_attack", [])[:10]
            ]
            examples = "".join(
                f"<li>{escape(p['home'])} vs {escape(p['away'])}: xG {p['expected_home_goals']} - "
                f"{p['expected_away_goals']}, P(H/D/A) "
                f"{p['probabilities']['home_win']:.0%}/{p['probabilities']['draw']:.0%}/"
                f"{p['probabilities']['away_win']:.0%}</li>"
                for p in report.get("example_predictions", [])
            )
            parts.append(
                f"<h2>Premier League model (standalone)</h2>"
                f"<p class=src>walk-forward holdout log loss {summary.get('model_log_loss')} "
                f"vs uniform {summary.get('uniform_log_loss')}; evaluated {summary.get('evaluated')} matches</p>"
                f"<h3>Strongest attacks</h3>{_table(['Team', 'Attack'], ratings_rows)}"
                f"<h3>Example forecasts</h3><ul>{examples}</ul>"
            )
    parts.append("</main></body></html>")
    return "".join(parts)


def page(tab: str, payload: dict[str, Any]) -> str:
    nav = "".join(
        f'<a href="/site/{key}"{" class=active" if key == tab else ""}>{label}</a>'
        for key, label in TABS
    )
    return f'{_STYLE}<nav>{nav}</nav>{render_tab(tab, payload)}'


def _attach_team_strength(payload: dict[str, Any]) -> None:
    report_path = Path("reports/team_strength_backtest.json")
    if report_path.exists():
        try:
            payload["team_strength"] = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass


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
                "deadline_time": None,
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
    return payload, snapshot, predictions


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
                self._add_personal_sections(payload, snapshot, predictions)
                return payload
        payload = build_cockpit(
            self._client_for_entry(),
            self.store,
            entry_id=self.entry_id,
            limit=30,
        )
        payload["data_source"] = "live fallback"
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
