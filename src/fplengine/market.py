"""Lightweight market intelligence derived from persisted observation snapshots.

This module never runs the expected-points model. Everything here either reads
official observed fields stored by the scheduled market poll (prices, ownership,
transfer counters, status/news) or computes transparent arithmetic deltas and
rates from them (velocity, acceleration, pressure).

Provenance contract:
- OBSERVED: official FPL bootstrap values captured by the poll.
- CALCULATED: deltas/rates computed in this file from those observations.
- MODELLED: only ``price_pressure``, which is an explicitly experimental
  heuristic and NOT the official FPL price-change threshold.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

PRESSURE_PROVENANCE = (
    "Experimental market-pressure indicator derived from observed transfer and "
    "ownership movement; not the official FPL price-change threshold."
)
PRESSURE_LEVELS = ("LOW", "MEDIUM", "HIGH", "VERY HIGH")
_PRESSURE_THRESHOLDS = ((0.05, "LOW"), (0.25, "MEDIUM"), (1.0, "HIGH"))
_ACCELERATION_CAPS = (0.5, 2.5)
_REFERENCE_WINDOWS_HOURS = (1.0, 6.0, 24.0)
_RETENTION_DAYS = 7

MARKET_PROVENANCE = {
    "observed": "official FPL prices, ownership, transfer counters, status and news",
    "calculated": "net-transfer velocity, ownership/price deltas and acceleration",
    "modelled": PRESSURE_PROVENANCE,
}


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO timestamp tolerating trailing 'Z' and non-string input."""
    if value is None or isinstance(value, datetime):
        return value if isinstance(value, datetime) else None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def hours_between(later: datetime, earlier: datetime) -> float:
    """Elapsed hours between two timestamps; negative gaps are clamped to zero."""
    return max(0.0, (later - earlier).total_seconds() / 3600.0)


def net_transfers(state: dict[str, Any]) -> int:
    return int(state.get("transfers_in_event") or 0) - int(
        state.get("transfers_out_event") or 0
    )


def select_reference_polls(
    polls: list[dict[str, Any]],
    now: datetime,
    windows: tuple[float, ...] = _REFERENCE_WINDOWS_HOURS,
) -> dict[float, dict[str, Any] | None]:
    """Pick, per window, the newest poll at least 75% of the window old.

    Using the actual age of the chosen poll (instead of pretending exactly 1h/6h/
    24h elapsed) keeps every derived figure honest under schedule drift. Polls are
    newest-first as returned by Store.market_polls().
    """
    parsed = []
    for row in polls:
        timestamp = parse_timestamp(row["captured_at"])
        if timestamp is not None:
            parsed.append((int(row["id"]), str(row["captured_at"]), hours_between(now, timestamp)))
    references: dict[float, dict[str, Any] | None] = {}
    for window in windows:
        chosen: dict[str, Any] | None = None
        best_age = float("inf")
        for poll_id, captured_at, age in parsed:
            # Newest poll that is already ~75% of the window old: smallest
            # qualifying age wins.
            if age >= window * 0.75 and age < best_age:
                chosen = {"poll_id": poll_id, "captured_at": captured_at, "age_hours": round(age, 2)}
                best_age = age
        references[window] = chosen
    return references


def pressure_level(intensity: float, acceleration_ratio: float | None) -> str:
    """Map transfer intensity (and optional acceleration) to a labelled level."""
    boost = 1.0
    if acceleration_ratio is not None:
        boost = min(_ACCELERATION_CAPS[1], max(_ACCELERATION_CAPS[0], acceleration_ratio))
    score = max(0.0, intensity) * boost
    for threshold, level in _PRESSURE_THRESHOLDS:
        if score < threshold:
            return level
    return PRESSURE_LEVELS[-1]


def player_market_row(
    player_id: int,
    current: dict[str, Any],
    references: dict[float, tuple[dict[str, Any] | None, float]],
    history_costs: list[tuple[str, int]] | None = None,
) -> dict[str, Any]:
    """Build one player's derived market features.

    ``references`` maps window hours to (reference_state_or_None, actual_age_hours).
    A missing reference state means the player was absent from that snapshot (new
    entrant); deltas are None rather than fabricated zeros.
    """
    current_net = net_transfers(current)
    row: dict[str, Any] = {
        "player_id": player_id,
        "price": int(current.get("now_cost") or 0) / 10.0,
        "ownership_percent": float(current.get("selected_percent") or 0.0),
        "status": current.get("status") or "",
        "news": current.get("news") or "",
        "chance_of_playing": current.get("chance_next"),
        "net_transfers": current_net,
        "net_transfers_1h": None,
        "net_transfers_6h": None,
        "net_transfers_24h": None,
        "velocity_per_hour_1h": None,
        "velocity_per_hour_6h": None,
        "ownership_change_1h": None,
        "ownership_change_6h": None,
        "ownership_change_24h": None,
        "price_change_24h": None,
        "last_price_change_at": None,
        "acceleration": None,
        "pressure_direction": "FLAT",
        "pressure_level": "LOW",
    }
    velocity_6h: float | None = None
    velocity_1h: float | None = None
    for window, (ref_state, age_hours) in references.items():
        key = f"{int(window)}h" if float(window).is_integer() else f"{window}h"
        if ref_state is None or age_hours <= 0:
            continue
        net_delta = current_net - net_transfers(ref_state)
        row[f"net_transfers_{key}"] = net_delta
        row[f"velocity_per_hour_{key}"] = round(net_delta / age_hours, 1)
        ownership_key = f"ownership_change_{key}"
        row[ownership_key] = round(
            float(current.get("selected_percent") or 0.0)
            - float(ref_state.get("selected_percent") or 0.0),
            3,
        )
        price_key = f"price_change_{key}"
        if price_key in row:
            row[price_key] = round(
                (int(current.get("now_cost") or 0) - int(ref_state.get("now_cost") or 0)) / 10.0,
                1,
            )
        if abs(window - 6.0) < 1e-9:
            velocity_6h = net_delta / age_hours
        if abs(window - 1.0) < 1e-9:
            velocity_1h = net_delta / age_hours

    if velocity_1h is not None and velocity_6h not in (None, 0.0):
        row["acceleration"] = round(velocity_1h / velocity_6h, 2)

    if history_costs:
        current_cost = int(current.get("now_cost") or 0)
        for captured_at, cost in reversed(history_costs):
            if cost != current_cost:
                row["last_price_change_at"] = captured_at
                break

    direction_value = velocity_6h
    if direction_value is None:
        direction_value = row["net_transfers_24h"]
    if direction_value is None:
        direction_value = current_net
    if direction_value > 0:
        row["pressure_direction"] = "UP"
    elif direction_value < 0:
        row["pressure_direction"] = "DOWN"

    ownership = max(float(row["ownership_percent"]), 0.01)
    denominator = max(500.0, ownership * 100.0)
    base_velocity = velocity_6h if velocity_6h is not None else 0.0
    intensity = abs(base_velocity) / denominator
    ratio = row["acceleration"] if isinstance(row["acceleration"], float) else None
    row["pressure_level"] = pressure_level(intensity, ratio)
    if direction_value == 0:
        row["pressure_level"] = "LOW"
        row["pressure_direction"] = "FLAT"
    return row


def build_market_view(
    polls: list[dict[str, Any]],
    states: dict[int, dict[int, dict[str, Any]]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble derived market features for every player in the newest poll."""
    moment = now or datetime.now(UTC)
    if not polls:
        return {"available": False, "reason": "no market polls stored yet"}
    current_poll = polls[0]
    current_states = states.get(current_poll["id"], {})
    references = select_reference_polls(polls, moment)
    ordered_polls = sorted(
        ((str(row["captured_at"]), int(row["id"])) for row in polls),
        key=lambda item: item[0],
    )
    rows: list[dict[str, Any]] = []
    for player_id, current in sorted(current_states.items()):
        per_player_refs: dict[float, tuple[dict[str, Any] | None, float]] = {}
        for window, reference in references.items():
            if reference is None:
                per_player_refs[window] = (None, 0.0)
            else:
                per_player_refs[window] = (
                    states.get(reference["poll_id"], {}).get(player_id),
                    reference["age_hours"],
                )
        history_costs: list[tuple[str, int]] = []
        for captured_at, poll_id in ordered_polls:
            state = states.get(poll_id, {}).get(player_id)
            if state is None:
                continue
            history_costs.append((captured_at, int(state.get("now_cost") or 0)))
        rows.append(player_market_row(player_id, current, per_player_refs, history_costs))
    return {
        "available": True,
        "captured_at": current_poll["captured_at"],
        "players": rows,
        "windows_hours": list(_REFERENCE_WINDOWS_HOURS),
        "retention_days": _RETENTION_DAYS,
        "poll_count": len(polls),
        "provenance": MARKET_PROVENANCE,
    }


def market_events(
    view: dict[str, Any],
    names_by_id: dict[int, str],
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Turn derived market movements into a typed, chronologically ordered feed.

    All events carry the freshness timestamp of the newest poll because deltas are
    computed against stored snapshots rather than streamed in real time.
    """
    if not view.get("available"):
        return []
    events: list[dict[str, Any]] = []
    for row in view["players"]:
        name = names_by_id.get(row["player_id"], f"Player {row['player_id']}")
        price_move = row.get("price_change_24h")
        if price_move:
            events.append(
                {
                    "type": "PRICE CHANGE",
                    "timestamp": view["captured_at"],
                    "name": name,
                    "detail": (
                        f"{name} is £{row['price']:.1f}m after "
                        f"{price_move:+.1f}m over the last day"
                    ),
                }
            )
        news = (row.get("news") or "").strip()
        if news:
            events.append(
                {
                    "type": "NEWS",
                    "timestamp": view["captured_at"],
                    "name": name,
                    "detail": f"{name}: {news[:80]}",
                }
            )
        if row["pressure_level"] in ("HIGH", "VERY HIGH"):
            verb = "buying" if row["pressure_direction"] == "UP" else "selling"
            events.append(
                {
                    "type": "TRANSFER SURGE",
                    "timestamp": view["captured_at"],
                    "name": name,
                    "detail": (
                        f"{name}: {verb} pressure {row['pressure_level']} "
                        f"({row['net_transfers_6h']:+d} net last 6h)"
                        if row["net_transfers_6h"] is not None
                        else f"{verb} pressure {row['pressure_level']} for {name}"
                    ),
                }
            )
        ownership_move = row.get("ownership_change_24h")
        if ownership_move is not None and abs(ownership_move) >= 0.5:
            events.append(
                {
                    "type": "OWNERSHIP SURGE",
                    "timestamp": view["captured_at"],
                    "name": name,
                    "detail": (
                        f"{name} ownership moved {ownership_move:+.1f}pp "
                        f"to {row['ownership_percent']:.1f}%"
                    ),
                }
            )
    return events[:limit]
