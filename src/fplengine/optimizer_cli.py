"""Command-line decision layer for exact FPL squad and transfer optimisation."""

from __future__ import annotations

import argparse
import json
from typing import Any

from .api_client import FPLClient
from .model import ExpectedPointsModel
from .optimizer import optimize_static_squad, optimize_transfers
from .service import latest_public_picks_event


def _future_events(snapshot: Any, start: int | None, horizon: int) -> list[int]:
    if horizon < 1 or horizon > 8:
        raise ValueError("horizon must be between 1 and 8 gameweeks")
    first = snapshot.target_event(start)
    ids = sorted(
        int(row["id"])
        for row in snapshot.bootstrap["events"]
        if int(row["id"]) >= first
    )
    events = ids[:horizon]
    if not events:
        raise ValueError("no future events are available")
    return events


def _weights(events: list[int], decay: float) -> dict[int, float]:
    if not 0 < decay <= 1:
        raise ValueError("decay must be in (0, 1]")
    return {event: decay**index for index, event in enumerate(events)}


def _predictions(snapshot: Any, events: list[int]) -> dict[int, list[Any]]:
    model = ExpectedPointsModel()
    return {event: model.predict(snapshot, event) for event in events}


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def command_squad(args: argparse.Namespace) -> None:
    client = FPLClient()
    snapshot = client.snapshot()
    events = _future_events(snapshot, args.event, args.horizon)
    result = optimize_static_squad(
        _predictions(snapshot, events),
        budget=args.budget,
        event_weights=_weights(events, args.decay),
        bench_weight=args.bench_weight,
        risk_penalty=args.risk_penalty,
    )
    payload = result.to_dict()
    payload["data_as_of"] = snapshot.fetched_at.isoformat()
    payload["deadline_source"] = "official FPL bootstrap-static"
    payload["decision"] = "best static squad across supplied horizon under current prices"
    _emit(payload)


def command_manager(args: argparse.Namespace) -> None:
    client = FPLClient()
    snapshot = client.snapshot()
    events = _future_events(snapshot, args.event, args.horizon)
    public_event = args.picks_event or latest_public_picks_event(snapshot)
    picks_payload = client.entry_picks(args.entry_id, public_event)
    current_ids = [int(row["element"]) for row in picks_payload.get("picks", [])]
    if len(current_ids) != 15:
        raise ValueError(f"public GW{public_event} picks did not contain a full 15-player squad")
    observed_bank = picks_payload.get("entry_history", {}).get("bank")
    bank = args.bank
    bank_source = "user-supplied"
    if bank is None:
        bank = float(observed_bank or 0) / 10.0
        bank_source = f"public GW{public_event} entry_history bank"
    result = optimize_transfers(
        current_ids,
        _predictions(snapshot, events),
        bank=bank,
        free_transfers=args.free_transfers,
        max_transfers=args.max_transfers,
        event_weights=_weights(events, args.decay),
        bench_weight=args.bench_weight,
        risk_penalty=args.risk_penalty,
    )
    payload = result.to_dict()
    payload["data_as_of"] = snapshot.fetched_at.isoformat()
    payload["manager"] = {
        "entry_id": args.entry_id,
        "public_squad_event": public_event,
        "bank": bank,
        "bank_source": bank_source,
        "free_transfers": args.free_transfers,
    }
    payload["limitations"] = [
        "Public FPL picks do not expose exact current selling prices for every owned player, so this command currently uses current purchase price as a conservative-data-availability approximation unless a future authenticated source is added.",
        "Banked free transfers are not reliably recoverable from the public picks payload; --free-transfers must reflect the manager's real current state.",
        "This pass chooses transfers now for a weighted future horizon; it does not yet optimize a sequence of transfer decisions on multiple future deadlines.",
    ]
    _emit(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fplopt", description="FPL Engine exact decision optimiser")
    subparsers = parser.add_subparsers(dest="command", required=True)

    squad = subparsers.add_parser("squad", help="Optimize a legal £100m squad over future GWs")
    squad.add_argument("--event", type=int, help="First target GW; defaults to next actionable GW")
    squad.add_argument("--horizon", type=int, default=3)
    squad.add_argument("--budget", type=float, default=100.0)
    squad.add_argument("--decay", type=float, default=0.90, help="Weight multiplier per later GW")
    squad.add_argument("--bench-weight", type=float, default=0.08)
    squad.add_argument("--risk-penalty", type=float, default=0.0)
    squad.set_defaults(func=command_squad)

    manager = subparsers.add_parser("manager", help="Optimize transfers from a public FPL squad")
    manager.add_argument("entry_id", type=int)
    manager.add_argument("--picks-event", type=int, help="Public squad GW to use as the starting squad")
    manager.add_argument("--event", type=int, help="First target prediction GW")
    manager.add_argument("--horizon", type=int, default=3)
    manager.add_argument("--free-transfers", type=int, required=True)
    manager.add_argument("--bank", type=float, help="Current money in bank; defaults to public picks history")
    manager.add_argument("--max-transfers", type=int, default=3)
    manager.add_argument("--decay", type=float, default=0.90)
    manager.add_argument("--bench-weight", type=float, default=0.08)
    manager.add_argument("--risk-penalty", type=float, default=0.0)
    manager.set_defaults(func=command_manager)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
