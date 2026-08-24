"""Gameweek Decision Cockpit: one assembled brief for the pre-deadline decision loop.

The cockpit is deliberately thin: it composes existing, versioned pieces (live
snapshot, xp-v0.2.0 predictions, stored point-in-time snapshots, the exact rules
optimizer) and adds no new modelling. Every section degrades independently, so a
missing history or optimizer failure never blanks the whole brief.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .api_client import Snapshot
from .model import ExpectedPointsModel, Prediction
from .optimizer import optimize_static_squad, optimize_transfers
from .rules import MAX_BANKED_FREE_TRANSFERS
from .service import build_report, latest_public_picks_event


def _fixture_rows(snapshot: Snapshot, event_id: int) -> list[dict[str, Any]]:
    teams = {
        int(row["id"]): row.get("short_name") or row.get("name", "")
        for row in snapshot.bootstrap["teams"]
    }
    rows = []
    fixture_teams: set[str] = set()
    for fixture in snapshot.fixtures:
        if int(fixture.get("event") or 0) != event_id:
            continue
        home_id, away_id = int(fixture["team_h"]), int(fixture["team_a"])
        home, away = teams.get(home_id, str(home_id)), teams.get(away_id, str(away_id))
        fixture_teams.update({home, away})
        rows.append(
            {
                "home": home,
                "away": away,
                "kickoff_utc": fixture.get("kickoff_time"),
                "started": bool(fixture.get("started")),
                "finished": bool(fixture.get("finished")),
                "home_score": fixture.get("team_h_score"),
                "away_score": fixture.get("team_a_score"),
            }
        )
    blanks = sorted(name for name in teams.values() if name and name not in fixture_teams)
    if blanks:
        rows.append({"note": "blank_gameweek_teams", "teams": blanks})
    return rows


def _top_components(row: Prediction, count: int = 3) -> dict[str, float]:
    components = {key: value for key, value in row.components.items() if abs(value) > 1e-9}
    positive = sorted(components.items(), key=lambda item: item[1], reverse=True)[:count]
    negative = sorted(components.items(), key=lambda item: item[1])[:1]
    return {key: round(value, 2) for key, value in dict(positive + negative).items() if value != 0}


def _rankings(predictions: list[Prediction], limit: int) -> list[dict[str, Any]]:
    rows = []
    for rank, row in enumerate(predictions[:limit], 1):
        entry = row.to_dict()
        entry["rank"] = rank
        entry["why_top_components"] = _top_components(row)
        rows.append(entry)
    return rows


def _captains(predictions: list[Prediction], limit: int) -> list[dict[str, Any]]:
    pool = [row for row in predictions if row.expected_minutes >= 55 and row.risk <= 0.45]
    ranked = sorted(pool, key=lambda row: row.expected_points, reverse=True)[:limit]
    return [
        {
            "player_id": row.player_id,
            "name": row.player_name,
            "team": row.team,
            "position": row.position,
            "expected_points": row.expected_points,
            "expected_minutes": row.expected_minutes,
            "risk": row.risk,
            "ceiling_upper_bound": row.upper_bound,
            "ownership_percent": row.ownership_percent,
        }
        for row in ranked
    ]


def _market_movers(predictions: list[Prediction], limit: int) -> dict[str, list[dict[str, Any]]]:
    eligible = [row for row in predictions if row.expected_minutes >= 30]

    def entry(row: Prediction) -> dict[str, Any]:
        return {
            "player_id": row.player_id,
            "name": row.player_name,
            "net_transfers": row.market_net_transfers,
            "momentum_percent": row.market_momentum_percent,
            "expected_points": row.expected_points,
            "risk": row.risk,
        }

    by_in = sorted(eligible, key=lambda row: row.market_net_transfers, reverse=True)[:limit]
    by_out = sorted(eligible, key=lambda row: row.market_net_transfers)[:limit]
    return {"most_bought": [entry(row) for row in by_in], "most_sold": [entry(row) for row in by_out]}


def snapshot_changes(store: Any, limit: int = 10) -> dict[str, Any]:
    """Diff the two most recent distinct ingestion runs from persistent storage."""
    try:
        previous, latest = store.latest_two_snapshots()
    except ValueError as exc:
        return {"available": False, "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 - missing schema/permissions degrade gracefully
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    changes: list[dict[str, Any]] = []
    for player_id in latest:
        before = previous.get(player_id)
        after = latest[player_id]
        if not before:
            continue
        price_delta = (after["now_cost"] - before["now_cost"]) / 10.0
        ownership_delta = round(after["selected_percent"] - before["selected_percent"], 3)
        status_changed = before["status"] != after["status"]
        news_added = bool(after["news"]) and after["news"] != before["news"]
        if price_delta or ownership_delta or status_changed or news_added:
            changes.append(
                {
                    "player_id": player_id,
                    "name": after["web_name"],
                    "price_change": price_delta,
                    "ownership_change_pp": ownership_delta,
                    "status_before": before["status"],
                    "status_after": after["status"],
                    "news": after["news"],
                    "transfers_in_event_delta": after["transfers_in_event"] - before["transfers_in_event"],
                    "transfers_out_event_delta": after["transfers_out_event"] - before["transfers_out_event"],
                }
            )
    risers = sorted(changes, key=lambda row: row["ownership_change_pp"], reverse=True)[:limit]
    fallers = sorted(changes, key=lambda row: row["ownership_change_pp"])[:limit]
    price_moves = sorted(changes, key=lambda row: abs(row["price_change"]), reverse=True)[:limit]
    flagged = [row for row in changes if row["status_before"] != row["status_after"] or row["news"]]
    return {
        "available": True,
        "previous_captured_at": min(row["captured_at"] for row in previous.values()),
        "latest_captured_at": max(row["captured_at"] for row in latest.values()),
        "ownership_risers": risers,
        "ownership_fallers": fallers,
        "price_moves": price_moves,
        "availability_or_news_changes": flagged[:limit],
    }


def player_detail(snapshot: Snapshot, predictions: list[Prediction], query: str) -> dict[str, Any]:
    needle = query.strip().lower()
    matches = [
        row
        for row in predictions
        if needle == str(row.player_id) or needle == row.player_name.lower()
        or needle in row.player_name.lower()
    ]
    if not matches:
        raise ValueError(f"No prediction matched player '{query}'")
    row = matches[0]
    detail = row.to_dict()
    detail["why_top_components"] = _top_components(row, count=6)
    event = snapshot.event(row.target_event)
    detail["deadline_utc"] = event.get("deadline_time")
    return detail


def _load_squad_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    squad_ids = payload.get("player_ids")
    if not isinstance(squad_ids, list) or len(squad_ids) != 15:
        raise ValueError("squad file must contain exactly 15 player_ids")
    if "bank" not in payload or "free_transfers" not in payload:
        raise ValueError("squad file must contain bank and free_transfers")
    if not 1 <= int(payload["free_transfers"]) <= MAX_BANKED_FREE_TRANSFERS:
        raise ValueError(f"free_transfers must be between 1 and {MAX_BANKED_FREE_TRANSFERS}")
    return payload


ROLL_GAIN_THRESHOLD = 0.8


def build_personal_sections(
    client: Any,
    snapshot: Snapshot,
    predictions: list[Prediction],
    entry_id: int,
    *,
    bank_override: float | None = None,
    free_transfers_override: int | None = None,
    selling_prices_file: Path | None = None,
    max_transfers: int = 2,
    roll_gain_threshold: float = ROLL_GAIN_THRESHOLD,
) -> dict[str, dict[str, Any]]:
    """MY TEAM / NEXT GW / manager-state sections driven by public entry data.

    Manager state is never guessed silently: every field carries a classification
    (VERIFIED from official endpoints, RECONSTRUCTED from history, APPROXIMATED by a
    documented default, USER-SUPPLIED via override, or UNKNOWN).
    """
    by_player = {row.player_id: row for row in predictions}
    elements = {int(row["id"]): row for row in snapshot.bootstrap["elements"]}
    teams = {
        int(row["id"]): row.get("short_name") or row.get("name", "")
        for row in snapshot.bootstrap["teams"]
    }
    event_id = predictions[0].target_event
    fixtures_by_team: dict[int, list[dict[str, Any]]] = {}
    for fixture in snapshot.fixtures:
        if int(fixture.get("event") or 0) != event_id:
            continue
        for side in ("team_h", "team_a"):
            fixtures_by_team.setdefault(int(fixture[side]), []).append(
                {
                    "opponent": teams.get(
                        int(fixture["team_a" if side == "team_h" else "team_h"]), "?"
                    ),
                    "venue": "H" if side == "team_h" else "A",
                }
            )

    entry = client.entry(entry_id)
    history = client.entry_history(entry_id)
    current_rows = [row for row in history.get("current", [])]
    latest_history = current_rows[-1] if current_rows else {}
    try:
        picks_event = latest_public_picks_event(snapshot)
    except ValueError:
        # Fresh seasons before GW1's deadline: fall back to the newest stored history row.
        if not current_rows:
            raise
        picks_event = int(current_rows[-1]["event"])
    picks_payload = client.entry_picks(entry_id, picks_event)
    picks = picks_payload.get("picks", [])
    if len(picks) != 15:
        raise ValueError(
            f"Entry {entry_id} has {len(picks)} picks for GW{picks_event}; expected 15"
        )

    selling_prices: dict[int, float] = {}
    if selling_prices_file is not None:
        raw = json.loads(selling_prices_file.read_text(encoding="utf-8"))
        selling_prices = {int(key): float(value) for key, value in raw.items()}

    bank_reconstructed = (
        float(latest_history["bank"]) / 10.0
        if latest_history.get("bank") is not None
        else None
    )
    last_event_transfers = int(latest_history.get("event_transfers") or 0)
    free_transfers_estimate = min(MAX_BANKED_FREE_TRANSFERS, 1 + max(0, 1 - last_event_transfers)) \
        if current_rows else 1
    effective_bank = (
        float(bank_override) if bank_override is not None else (
            bank_reconstructed if bank_reconstructed is not None else 0.0
        )
    )
    effective_free_transfers = int(
        free_transfers_override if free_transfers_override is not None else free_transfers_estimate
    )
    manager_state = {
        "squad_and_lineup": {
            "value": f"GW{picks_event} official picks",
            "classification": "VERIFIED",
        },
        "bank": {
            "value": round(effective_bank, 1),
            "classification": (
                "USER-SUPPLIED" if bank_override is not None
                else "RECONSTRUCTED" if bank_reconstructed is not None
                else "UNKNOWN_ASSUMED_0"
            ),
            "note": "from last finished GW; ignores transfers made since",
        },
        "free_transfers": {
            "value": effective_free_transfers,
            "classification": (
                "USER-SUPPLIED" if free_transfers_override is not None else "APPROXIMATED"
            ),
            "note": f"inferred as saved after {last_event_transfers} transfer(s); banking cannot be observed publicly",
        },
        "selling_prices": {
            "value": "current prices" if not selling_prices else "supplied map",
            "classification": "APPROXIMATED" if not selling_prices else "USER-SUPPLIED",
            "note": "true FPL selling price (half-profit rule) needs purchase history",
        },
        "chips": {
            "value": history.get("chips") or [],
            "classification": "VERIFIED (used chips only); remaining chip state NOT YET MODELLED",
        },
    }

    my_team_rows: list[dict[str, Any]] = []
    missing_predictions: list[int] = []
    for pick in sorted(picks, key=lambda row: int(row["position"])):
        player_id = int(pick["element"])
        prediction = by_player.get(player_id)
        element = elements.get(player_id, {})
        slot = int(pick["position"])
        row_out: dict[str, Any] = {
            "player_id": player_id,
            "name": element.get("web_name"),
            "position_slot": slot,
            "role": "bench" if slot >= 12 else "starter",
            "is_captain": bool(pick.get("is_captain")),
            "is_vice_captain": bool(pick.get("is_vice_captain")),
            "team": teams.get(int(element.get("team", 0)), "?"),
            "fixture": fixtures_by_team.get(int(element.get("team", 0)), []),
            "availability_status": element.get("status"),
            "availability_news": element.get("news") or "",
            "chance_of_playing": element.get("chance_of_playing_next_round"),
            "price": round(int(element.get("now_cost", 0)) / 10.0, 1),
            "ownership_percent": float(element.get("selected_by_percent") or 0),
            "classification_observed": "official FPL bootstrap + entry picks",
        }
        if prediction is None:
            missing_predictions.append(player_id)
            my_team_rows.append(row_out)
            continue
        row_out.update(
            {
                "expected_minutes": prediction.expected_minutes,
                "expected_points": prediction.expected_points,
                "risk": prediction.risk,
                "range": [prediction.lower_bound, prediction.upper_bound],
                "why_top_components": _top_components(prediction),
                "model_version": prediction.model_version,
                "classification_modelled": "xp-v0.2.0 predictions",
            }
        )
        my_team_rows.append(row_out)

    weak_spots = [
        {
            "player_id": row["player_id"],
            "name": row["name"],
            "reason": reason,
        }
        for row in my_team_rows
        if row["position_slot"] <= 11
        for reason in (
            ([f"status={row['availability_status']}: {row['availability_news']}"] if row["availability_status"] != "a" else [])
            + (["low xMins"] if row.get("expected_minutes", 90) < 40 else [])
            + (["high risk"] if row.get("risk", 0) > 0.35 else [])
        )
    ]
    squad_ids = {row["player_id"] for row in my_team_rows}
    possible_buys = [
        {
            "player_id": row.player_id,
            "name": row.player_name,
            "expected_points": row.expected_points,
            "price": row.price,
            "differential_score": row.differential_score,
        }
        for row in predictions
        if row.player_id not in squad_ids and row.expected_minutes >= 40
    ][:8]

    horizon = {event_id: predictions}
    try:
        roll_plan = optimize_transfers(
            squad_ids,
            horizon,
            bank=effective_bank,
            free_transfers=max(1, effective_free_transfers),
            selling_prices=selling_prices or None,
            max_transfers=0,
        )
        plan_one = optimize_transfers(
            squad_ids,
            horizon,
            bank=effective_bank,
            free_transfers=max(1, effective_free_transfers),
            selling_prices=selling_prices or None,
            max_transfers=1,
        )
        plan_two = optimize_transfers(
            squad_ids,
            horizon,
            bank=effective_bank,
            free_transfers=max(1, effective_free_transfers),
            selling_prices=selling_prices or None,
            max_transfers=min(2, max_transfers),
        )
    except Exception as exc:  # noqa: BLE001 - optimizer failure must not kill MY TEAM
        next_gw = {"error": f"{type(exc).__name__}: {exc}"}
        return {
            "my_team": {
                "players": my_team_rows,
                "missing_predictions": missing_predictions,
                "weak_spots": weak_spots,
                "possible_buys": possible_buys,
            },
            "next_gw": next_gw,
            "manager_state": manager_state,
        }

    def plan_view(plan):
        lineup = plan.lineups[0] if plan.lineups else None
        return {
            "transfers_in": [row.name for row in plan.transfers_in],
            "transfers_out": [row.name for row in plan.transfers_out],
            "hit_cost": plan.hit_cost,
            "projected_points": plan.weighted_projected_points,
            "captain": plan.lineups[0].captain.name if plan.lineups else None,
            "vice_captain": plan.lineups[0].vice_captain.name if plan.lineups else None,
            "starters": [row.name for row in lineup.starters] if lineup else [],
            "bench_order": (
                ([lineup.bench_goalkeeper.name] + [row.name for row in lineup.bench_outfield])
                if lineup else []
            ),
        }

    roll_projection = roll_plan.weighted_projected_points
    gain_one = plan_one.weighted_projected_points - roll_projection
    gain_two = plan_two.weighted_projected_points - plan_one.weighted_projected_points
    if gain_one <= roll_gain_threshold and gain_two <= roll_gain_threshold:
        recommendation = {
            "action": "ROLL",
            "reason": (
                f"best transfer plan gains only {max(gain_one, gain_two + gain_one - gain_one):.2f} "
                f"points net; keeping the free transfer is worth more"
            ),
            "recommended_plan": plan_view(roll_plan),
        }
    elif plan_two.weighted_projected_points > plan_one.weighted_projected_points + 1.0:
        recommendation = {
            "action": "TRANSFER (two)",
            "reason": f"second transfer adds {gain_two:.2f} points beyond the first",
            "recommended_plan": plan_view(plan_two),
        }
    else:
        recommendation = {
            "action": "TRANSFER (one)",
            "reason": f"single transfer gains {gain_one:.2f} points net over rolling",
            "recommended_plan": plan_view(plan_one),
        }
    approximate = any(
        manager_state[field]["classification"] != "USER-SUPPLIED"
        for field in ("bank", "free_transfers", "selling_prices")
    )
    recommendation["state_label"] = "APPROXIMATE" if approximate else "VERIFIED_INPUTS"

    next_gw = {
        "target_event": event_id,
        "roll_plan": plan_view(roll_plan),
        "best_single_transfer": plan_view(plan_one),
        "gain_over_roll_net_of_hits": round(gain_one, 3),
        "best_two_transfer": plan_view(plan_two),
        "recommendation": recommendation,
        "possible_sells": [
            row["name"]
            for row in sorted(my_team_rows, key=lambda row: row.get("expected_points", 0))
            if row["position_slot"] <= 11
        ][:4],
        "injury_rotation_concerns": [
            {
                "name": row["name"],
                "status": row["availability_status"],
                "news": row["availability_news"],
            }
            for row in my_team_rows
            if row["availability_status"] != "a" or row["availability_news"]
        ],
    }
    return {
        "my_team": {
            "entry_id": entry_id,
            "team_name": entry.get("name"),
            "picks_verified_event": picks_event,
            "players": my_team_rows,
            "missing_predictions": missing_predictions,
            "weak_spots": weak_spots,
            "possible_buys": possible_buys,
        },
        "next_gw": next_gw,
        "manager_state": manager_state,
    }


def _optimization_sections(
    predictions: list[Prediction],
    *,
    squad_file: Path | None,
    max_transfers: int = 5,
) -> dict[str, Any]:
    event_id = predictions[0].target_event
    sections: dict[str, Any] = {}
    try:
        sections["benchmark_squad"] = optimize_static_squad(
            {event_id: predictions}, budget=100.0
        ).to_dict()
    except Exception as exc:  # noqa: BLE001 - cockpit sections fail independently
        sections["benchmark_squad"] = {"error": f"{type(exc).__name__}: {exc}"}
    if squad_file is not None:
        try:
            squad = _load_squad_file(squad_file)
            selling_prices = {
                int(player_id): float(price)
                for player_id, price in (squad.get("selling_prices") or {}).items()
            }
            sections["your_transfers"] = optimize_transfers(
                squad["player_ids"],
                {event_id: predictions},
                bank=float(squad["bank"]),
                free_transfers=int(squad["free_transfers"]),
                selling_prices=selling_prices or None,
                max_transfers=int(squad.get("max_transfers", max_transfers)),
            ).to_dict()
        except Exception as exc:  # noqa: BLE001 - cockpit sections fail independently
            sections["your_transfers"] = {"error": f"{type(exc).__name__}: {exc}"}
    else:
        sections["your_transfers"] = {
            "skipped": "provide --squad-file with player_ids, bank and free_transfers "
            "for a personal transfer plan"
        }
    return sections


def assemble_cockpit(
    snapshot: Snapshot,
    predictions: list[Prediction],
    *,
    store: Any = None,
    limit: int = 15,
    squad_file: Path | None = None,
    player_query: str | None = None,
) -> dict[str, Any]:
    """Assemble every cockpit section from a live snapshot and versioned predictions."""
    event_id = predictions[0].target_event
    event_row = snapshot.event(event_id)
    report = build_report(snapshot, predictions, limit)

    cockpit: dict[str, Any] = {
        "metadata": {
            **report["metadata"],
            "deadline_utc": event_row.get("deadline_time"),
            "cockpit_version": "cockpit-v0.1.0",
        },
        "warnings": list(report["warnings"]),
        "fixtures": _fixture_rows(snapshot, event_id),
        "rankings": _rankings(predictions, limit),
        "captains": _captains(predictions, limit),
        "differentials": report["differentials"][:limit],
        "value": report["value"][:limit],
        "market_movers": _market_movers(predictions, limit),
        "changes_since_previous_snapshot": (
            snapshot_changes(store) if store is not None else {"available": False}
        ),
        "uncertainty_notes": [
            "Bounds are variance-based ranges, not calibrated intervals: starters were "
            "covered ~72% historically versus an ~85% target; the validated x2 upper-tail "
            "widening (xp-v0.3-interval-calibration) is not yet adopted.",
            "Risk summarizes availability and minutes uncertainty only.",
        ],
    }
    cockpit.update(_optimization_sections(predictions, squad_file=squad_file))
    if player_query:
        try:
            cockpit["player_detail"] = player_detail(snapshot, predictions, player_query)
        except ValueError as exc:
            cockpit["player_detail"] = {"error": str(exc)}
    return cockpit


def build_cockpit(
    client: Any,
    store: Any = None,
    *,
    entry_id: int | None = None,
    event: int | None = None,
    limit: int = 15,
    squad_file: Path | None = None,
    player_query: str | None = None,
    bank_override: float | None = None,
    free_transfers_override: int | None = None,
    selling_prices_file: Path | None = None,
) -> dict[str, Any]:
    """Fetch live data and assemble the cockpit; sections degrade independently."""
    snapshot = client.snapshot()
    predictions = ExpectedPointsModel().predict(snapshot, event)
    cockpit = assemble_cockpit(
        snapshot,
        predictions,
        store=store,
        limit=limit,
        squad_file=squad_file,
        player_query=player_query,
    )
    if entry_id is not None:
        try:
            personal = build_personal_sections(
                client,
                snapshot,
                predictions,
                entry_id,
                bank_override=bank_override,
                free_transfers_override=free_transfers_override,
                selling_prices_file=selling_prices_file,
            )
        except Exception as exc:  # noqa: BLE001 - manager context must not break briefs
            personal = {"my_team": {"error": f"{type(exc).__name__}: {exc}"}}
        cockpit["my_team"] = personal.get("my_team")
        cockpit["next_gw"] = personal.get("next_gw")
        cockpit["manager_state"] = personal.get("manager_state")
        if "error" in personal.get("my_team", {}):
            cockpit.setdefault("warnings", []).append(
                f"Personal team section failed: {personal['my_team']['error']}"
            )
    return cockpit


def render_text(cockpit: dict[str, Any]) -> str:
    """Compact human-readable brief; JSON remains the canonical output."""
    meta = cockpit["metadata"]
    lines = [
        f"GW{meta['target_event']} Decision Cockpit | deadline {meta['deadline_utc']}",
        f"model {meta['model_version']} | as of {meta['data_as_of']} | players {meta['player_count']}",
    ]
    lines.extend(f"WARNING: {warning}" for warning in cockpit["warnings"])
    lines.append("")
    lines.append("Fixtures")
    for fixture in cockpit["fixtures"]:
        if fixture.get("note"):
            lines.append(f"  blank: {', '.join(fixture['teams'])}")
        else:
            score = (
                f" {fixture['home_score']}-{fixture['away_score']} "
                if fixture["finished"]
                else ""
            )
            state = "FT" if fixture["finished"] else ("live" if fixture["started"] else "upcoming")
            lines.append(f"  {fixture['home']} vs {fixture['away']}{score} ({state})")
    lines.append("")
    lines.append("Rankings (xP / xMins / risk / range)")
    for row in cockpit["rankings"]:
        lines.append(
            f"  {row['rank']:2d}. {row['player_name'][:18]:18s} {row['team']:4s} {row['position']:4s}"
            f" xP {row['expected_points']:5.2f} xM {row['expected_minutes']:5.1f}"
            f" risk {row['risk']:.2f} [{row['lower_bound']:.1f},{row['upper_bound']:.1f}]"
            f" why={row['why_top_components']}"
        )
    lines.append("")
    lines.append("Captain candidates (ceiling in brackets)")
    for row in cockpit["captains"]:
        lines.append(
            f"  {row['name'][:18]:18s} xP {row['expected_points']:5.2f}"
            f" ceiling [{row['ceiling_upper_bound']:.1f}] own {row['ownership_percent']:.1f}%"
        )
    movers = cockpit["market_movers"]
    lines.append("")
    lines.append("Market movers")
    lines.append("  bought: " + ", ".join(f"{r['name']} (+{r['net_transfers']})" for r in movers["most_bought"][:5]))
    lines.append("  sold:   " + ", ".join(f"{r['name']} ({r['net_transfers']})" for r in movers["most_sold"][:5]))
    changes = cockpit["changes_since_previous_snapshot"]
    lines.append("")
    if changes.get("available"):
        lines.append(
            f"Changes since {changes['previous_captured_at']} "
            f"(latest {changes['latest_captured_at']})"
        )
        for row in changes["price_moves"][:5]:
            sign = "+" if row["price_change"] > 0 else ""
            lines.append(f"  price {row['name'][:18]:18s} {sign}{row['price_change']:.1f}")
        for row in changes["availability_or_news_changes"][:5]:
            lines.append(f"  news {row['name'][:18]:18s} {row['news'][:60]}")
        if not changes["price_moves"] and not changes["availability_or_news_changes"]:
            lines.append("  no material price/news/ownership movement recorded")
    else:
        lines.append(f"Changes unavailable: {changes.get('reason', 'no stored snapshots')}")
    benchmark = cockpit.get("benchmark_squad", {})
    lines.append("")
    if "error" in benchmark:
        lines.append(f"Benchmark squad failed: {benchmark['error']}")
    elif benchmark:
        lineup = benchmark.get("lineups", [{}])[0]
        captain = lineup.get("captain", {})
        lines.append(
            f"Benchmark squad: cost {benchmark.get('squad_cost')} bank {benchmark.get('bank_after')}"
            f" | GW{lineup.get('event')} captain {captain.get('name')}"
            f" | projected {lineup.get('projected_points')}"
        )
    transfers = cockpit.get("your_transfers", {})
    lines.append("")
    if transfers.get("skipped"):
        lines.append(f"Your transfers: {transfers['skipped']}")
    elif "error" in transfers:
        lines.append(f"Your transfers failed: {transfers['error']}")
    else:
        ins = ", ".join(f"{row['name']}" for row in transfers.get("transfers_in", [])) or "none"
        outs = ", ".join(f"{row['name']}" for row in transfers.get("transfers_out", [])) or "none"
        lines.append(
            f"Your plan: IN {ins} | OUT {outs} | hits {transfers.get('hit_cost')}"
            f" | projected {transfers.get('weighted_projected_points')}"
        )
    detail = cockpit.get("player_detail")
    if detail:
        lines.append("")
        if "error" in detail:
            lines.append(f"Player detail: {detail['error']}")
        else:
            lines.append(
                f"Detail {detail['player_name']}: xP {detail['expected_points']}"
                f" xM {detail['expected_minutes']} risk {detail['risk']}"
                f" range [{detail['lower_bound']}, {detail['upper_bound']}]"
                f" why={detail['why_top_components']}"
            )
    my_team = cockpit.get("my_team")
    if my_team:
        lines.append("")
        if "error" in my_team:
            lines.append(f"MY TEAM failed: {my_team['error']}")
        else:
            lines.append(f"MY TEAM {my_team.get('team_name')} (verified GW{my_team.get('picks_verified_event')})")
            for row in my_team["players"]:
                marker = "(C)" if row["is_captain"] else "(V)" if row["is_vice_captain"] else ""
                slot = row["position_slot"]
                bench = "bench" if slot >= 12 else ""
                xpart = (
                    f"xP {row.get('expected_points', 0):4.1f} xM {row.get('expected_minutes', 0):5.1f}"
                    if "expected_points" in row
                    else "no prediction"
                )
                status = row["availability_status"]
                flag = "" if status == "a" else f" [{status}] {row['availability_news'][:40]}"
                fixture = "/".join(
                    f"{f['venue']} {f['opponent']}" for f in row.get("fixture", [])
                )
                lines.append(
                    f"  {slot:2d}. {str(row['name'])[:16]:16s}{marker:3s} {row['team']:3s}"
                    f" {fixture:8s} {xpart} £{row['price']:.1f} own {row['ownership_percent']:4.1f}%"
                    f" {bench}{flag}"
                )
            if my_team.get("weak_spots"):
                lines.append("  weak spots: " + "; ".join(
                    f"{row['name']} ({row['reason']})" for row in my_team["weak_spots"][:6]
                ))
    next_gw = cockpit.get("next_gw")
    if next_gw and "error" not in next_gw:
        rec = next_gw["recommendation"]
        lines.append("")
        lines.append(
            f"NEXT GW RECOMMENDATION: {rec['action']} [{rec['state_label']}] - {rec['reason']}"
        )
        plan = rec["recommended_plan"]
        if rec["action"] != "ROLL":
            lines.append(
                f"  IN: {', '.join(plan['transfers_in']) or '-'} | "
                f"OUT: {', '.join(plan['transfers_out']) or '-'} | hits {plan['hit_cost']}"
            )
        lines.append(
            f"  projected {plan['projected_points']} | captain {plan['captain']}"
            f" | vice {plan['vice_captain']}"
        )
        lines.append(f"  bench order: {', '.join(plan['bench_order'])}")
        state = cockpit.get("manager_state", {})
        approximations = [
            f"{name}={state[name]['value']} ({state[name]['classification']})"
            for name in ("bank", "free_transfers", "selling_prices")
            if name in state and state[name]["classification"] != "USER-SUPPLIED"
        ]
        if approximations:
            lines.append("  manager state used: " + "; ".join(approximations))
    lines.extend(cockpit.get("uncertainty_notes", []))
    return "\n".join(lines)
