"""Command line interface for data, predictions, managers, and evaluation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .api_client import FPLAPIError, FPLClient
from .benchmark import SeasonArchive, benchmark_season, write_benchmark_report
from .cockpit import build_cockpit, render_text
from .http_api import serve
from .model import ExpectedPointsModel, Prediction
from .priors import build_prior_payload, write_prior_payload
from .service import analyze_manager, analyze_manager_cohort, build_report, filter_rankings
from .storage import Store


def _json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _table(rows: Iterable[Prediction]) -> None:
    selected = list(rows)
    if not selected:
        print("No players matched the filters.")
        return
    headers = ("#", "Player", "Team", "Pos", "Price", "xMins", "xP", "Own%", "Risk", "Range")
    widths = (3, 20, 5, 4, 5, 7, 6, 7, 6, 13)
    print(" ".join(value.ljust(width) for value, width in zip(headers, widths)))
    print(" ".join("-" * width for width in widths))
    for index, row in enumerate(selected, 1):
        values = (
            str(index),
            row.player_name[:20],
            row.team,
            row.position,
            f"{row.price:.1f}",
            f"{row.expected_minutes:.1f}",
            f"{row.expected_points:.2f}",
            f"{row.ownership_percent:.1f}",
            f"{row.risk:.2f}",
            f"{row.lower_bound:.1f}-{row.upper_bound:.1f}",
        )
        print(" ".join(value.ljust(width) for value, width in zip(values, widths)))


def _live(args: argparse.Namespace) -> tuple[Any, list[Prediction]]:
    client = FPLClient(
        timeout_seconds=float(os.getenv("FPLENGINE_HTTP_TIMEOUT_SECONDS", "30")),
        max_retries=int(os.getenv("FPLENGINE_HTTP_MAX_RETRIES", "3")),
    )
    snapshot = client.snapshot()
    predictions = ExpectedPointsModel().predict(snapshot, args.event)
    return snapshot, predictions


def command_run(args: argparse.Namespace) -> None:
    snapshot, predictions = _live(args)
    store = Store(args.database_url)
    store.initialize()
    ingestion_id, inserted = store.save_snapshot(snapshot)
    run_id = store.save_predictions(ingestion_id, snapshot, predictions)
    payload = build_report(snapshot, predictions, args.limit)
    payload["persistence"] = {
        "database": "neon-postgres" if store.is_postgres else "local-sqlite-development-cache",
        "ingestion_run_id": ingestion_id,
        "prediction_run_id": run_id,
        "new_source_snapshot": inserted,
    }
    if args.json:
        _json(payload)
    else:
        metadata = payload["metadata"]
        print(
            f"FPL Engine {metadata['model_version']} | target GW{metadata['target_event']} | "
            f"as of {metadata['data_as_of']}"
        )
        for warning in payload["warnings"]:
            print(f"WARNING: {warning}")
        print("\nTop rankings")
        _table(predictions[: args.limit])
        print(f"\nStored ingestion {ingestion_id} and prediction run {run_id}.")


def command_rankings(args: argparse.Namespace) -> None:
    snapshot, predictions = _live(args)
    rows = filter_rankings(
        predictions,
        position=args.position,
        max_price=args.max_price,
        max_ownership=args.max_ownership,
        min_minutes=args.min_minutes,
        limit=args.limit,
    )
    if args.json:
        _json(
            {
                "data_as_of": snapshot.fetched_at.isoformat(),
                "target_event": predictions[0].target_event,
                "model_version": predictions[0].model_version,
                "results": [row.to_dict() for row in rows],
            }
        )
    else:
        _table(rows)


def command_report(args: argparse.Namespace) -> None:
    snapshot, predictions = _live(args)
    _json(build_report(snapshot, predictions, args.limit))


def command_cockpit(args: argparse.Namespace) -> None:
    client = FPLClient(
        timeout_seconds=float(os.getenv("FPLENGINE_HTTP_TIMEOUT_SECONDS", "30")),
        max_retries=int(os.getenv("FPLENGINE_HTTP_MAX_RETRIES", "3")),
    )
    store = Store(args.database_url)
    # Schema migration is a deployment concern: the production application role is
    # least-privilege and must never need DDL. Only local SQLite self-initialises.
    if not store.is_postgres or args.init_schema:
        store.initialize()
    cockpit = build_cockpit(
        client,
        store,
        entry_id=args.entry_id,
        event=args.event,
        limit=args.limit,
        squad_file=Path(args.squad_file) if args.squad_file else None,
        player_query=args.player,
        bank_override=args.bank,
        free_transfers_override=args.free_transfers,
        selling_prices_file=Path(args.selling_prices) if args.selling_prices else None,
    )
    if args.json:
        _json(cockpit)
    else:
        print(render_text(cockpit))


def command_manager(args: argparse.Namespace) -> None:
    client = FPLClient()
    snapshot = client.snapshot()
    predictions = ExpectedPointsModel().predict(snapshot, args.event)
    _json(analyze_manager(client, snapshot, predictions, args.entry_id, args.picks_event))


def command_elite(args: argparse.Namespace) -> None:
    client = FPLClient()
    snapshot = client.snapshot()
    predictions = ExpectedPointsModel().predict(snapshot, args.event)
    _json(
        analyze_manager_cohort(
            client,
            snapshot,
            predictions,
            league_id=args.league_id,
            sample_size=args.sample,
            picks_event=args.picks_event,
            candidate_pool_size=args.candidate_pool,
            minimum_past_seasons=args.minimum_past_seasons,
            include_transfers=not args.no_transfers,
        )
    )


def command_evaluate(args: argparse.Namespace) -> None:
    client = FPLClient()
    snapshot = client.snapshot()
    event = snapshot.event(args.event_id)
    if not event.get("finished"):
        raise ValueError(f"GW{args.event_id} is not final; evaluation would use incomplete actuals")
    payload = client.event_live(args.event_id)
    actual = {
        int(row["id"]): int(row.get("stats", {}).get("total_points") or 0)
        for row in payload.get("elements", [])
    }
    result = Store(args.database_url).evaluate(
        args.event_id, actual, event["deadline_time"], policy=args.policy
    )
    result.update(
        {
            "event": args.event_id,
            "actual_source": "official FPL event-live endpoint",
            "evaluated_only_after_final": True,
        }
    )
    _json(result)


def command_evaluate_latest(args: argparse.Namespace) -> None:
    client = FPLClient()
    snapshot = client.snapshot()
    finished = [row for row in snapshot.bootstrap["events"] if row.get("finished")]
    if not finished:
        _json({"status": "skipped", "reason": "No gameweek is final yet"})
        return
    event = max(finished, key=lambda row: int(row["id"]))
    event_id = int(event["id"])
    payload = client.event_live(event_id)
    actual = {
        int(row["id"]): int(row.get("stats", {}).get("total_points") or 0)
        for row in payload.get("elements", [])
    }
    try:
        result = Store(args.database_url).evaluate(
            event_id, actual, event["deadline_time"], policy=args.policy
        )
    except ValueError as exc:
        _json({"status": "skipped", "event": event_id, "reason": str(exc)})
        return
    result.update(
        {
            "status": "evaluated",
            "event": event_id,
            "actual_source": "official FPL event-live endpoint",
            "leakage_guard": "only prediction runs generated on or before the deadline",
        }
    )
    _json(result)


def command_init_db(args: argparse.Namespace) -> None:
    store = Store(args.database_url)
    store.initialize()
    _json({"status": "initialized", "database": "postgres" if store.is_postgres else "sqlite"})


def command_build_priors(args: argparse.Namespace) -> None:
    payload = build_prior_payload(Path(args.season_dir), args.season)
    write_prior_payload(payload, Path(args.output))
    _json(
        {
            "status": "written",
            "season": args.season,
            "players": len(payload["players"]),
            "teams": len(payload["teams"]),
            "output": str(Path(args.output).resolve()),
        }
    )


def command_benchmark(args: argparse.Namespace) -> None:
    priors = json.loads(Path(args.priors).read_text(encoding="utf-8"))
    report = benchmark_season(
        SeasonArchive(Path(args.season_dir)),
        priors,
        first_event=args.from_event,
        last_event=args.to_event,
    )
    if args.output:
        write_benchmark_report(report, Path(args.output))
    _json(report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fplengine", description="FPL Engine v0.2")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--event", type=int, help="Target gameweek; defaults to the next actionable event")
    common.add_argument("--limit", type=int, default=15)

    run = subparsers.add_parser("run", parents=[common], help="Ingest, predict, persist, and report")
    run.add_argument("--database-url")
    run.add_argument("--json", action="store_true")
    run.set_defaults(func=command_run)

    rankings = subparsers.add_parser("rankings", parents=[common], help="Rank live players")
    rankings.add_argument("--position", choices=["GK", "DEF", "MID", "FWD"])
    rankings.add_argument("--max-price", type=float)
    rankings.add_argument("--max-ownership", type=float)
    rankings.add_argument("--min-minutes", type=float, default=0)
    rankings.add_argument("--json", action="store_true")
    rankings.set_defaults(func=command_rankings)

    report = subparsers.add_parser("report", parents=[common], help="Emit the full JSON decision report")
    report.set_defaults(func=command_report)

    cockpit = subparsers.add_parser(
        "cockpit", parents=[common], help="Assemble the gameweek decision brief"
    )
    cockpit.add_argument("--database-url")
    cockpit.add_argument("--entry-id", type=int, help="Public FPL entry for MY TEAM / NEXT GW sections")
    cockpit.add_argument("--bank", type=float, help="USER-SUPPLIED bank in £ millions")
    cockpit.add_argument(
        "--free-transfers",
        type=int,
        help="USER-SUPPLIED banked free transfers (1-5); otherwise APPROXIMATED",
    )
    cockpit.add_argument(
        "--selling-prices",
        help="JSON file mapping player_id to exact selling price for transfer plans",
    )
    cockpit.add_argument(
        "--init-schema",
        action="store_true",
        help="Apply the schema even on Postgres (deployment use only)",
    )
    cockpit.add_argument("--squad-file", help="JSON with player_ids(15), bank, free_transfers")
    cockpit.add_argument("--player", help="Add a player detail section by id or name substring")
    cockpit.add_argument("--json", action="store_true")
    cockpit.set_defaults(func=command_cockpit)

    manager = subparsers.add_parser("manager", help="Analyse a public FPL entry")
    manager.add_argument("entry_id", type=int)
    manager.add_argument("--event", type=int, help="Prediction target gameweek")
    manager.add_argument("--picks-event", type=int, help="Already-deadlined picks gameweek")
    manager.set_defaults(func=command_manager)

    elite = subparsers.add_parser("elite", help="Analyse consensus in a strong-manager cohort")
    elite.add_argument("--league-id", type=int, default=321, help="Defaults to Top 1%% 25/26")
    elite.add_argument("--sample", type=int, default=25)
    elite.add_argument("--candidate-pool", type=int, help="Candidates to history-screen, max 200")
    elite.add_argument("--minimum-past-seasons", type=int, default=2)
    elite.add_argument("--no-transfers", action="store_true", help="Skip transfer aggregation")
    elite.add_argument("--event", type=int, help="Prediction target gameweek")
    elite.add_argument("--picks-event", type=int, help="Already-deadlined picks gameweek")
    elite.set_defaults(func=command_elite)

    evaluate = subparsers.add_parser("evaluate", help="Score a stored prediction run")
    evaluate.add_argument("event_id", type=int)
    evaluate.add_argument("--database-url")
    evaluate.add_argument(
        "--policy",
        choices=["earliest_predeadline", "latest_predeadline"],
        default="latest_predeadline",
    )
    evaluate.set_defaults(func=command_evaluate)

    evaluate_latest = subparsers.add_parser(
        "evaluate-latest", help="Evaluate the latest final gameweek if a pre-deadline run exists"
    )
    evaluate_latest.add_argument("--database-url")
    evaluate_latest.add_argument(
        "--policy",
        choices=["earliest_predeadline", "latest_predeadline"],
        default="latest_predeadline",
    )
    evaluate_latest.set_defaults(func=command_evaluate_latest)

    init_db = subparsers.add_parser("init-db", help="Apply the idempotent database schema")
    init_db.add_argument("--database-url")
    init_db.set_defaults(func=command_init_db)

    build_priors = subparsers.add_parser(
        "build-priors", help="Build compact prior-season evidence from a Vaastav archive"
    )
    build_priors.add_argument("season_dir")
    build_priors.add_argument("--season", required=True)
    build_priors.add_argument("--output", required=True)
    build_priors.set_defaults(func=command_build_priors)

    benchmark = subparsers.add_parser(
        "benchmark", help="Run a leakage-aware walk-forward historical benchmark"
    )
    benchmark.add_argument("season_dir")
    benchmark.add_argument("--priors", required=True)
    benchmark.add_argument("--from-event", type=int, default=6)
    benchmark.add_argument("--to-event", type=int, default=38)
    benchmark.add_argument("--output")
    benchmark.set_defaults(func=command_benchmark)

    api = subparsers.add_parser("api", help="Serve the read-only JSON API")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--ttl", type=int, default=900)
    api.set_defaults(func=lambda args: serve(args.host, args.port, args.ttl))
    return parser


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (FPLAPIError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
