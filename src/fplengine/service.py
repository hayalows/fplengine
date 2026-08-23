"""Application services that turn predictions into actionable FPL intelligence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from .api_client import FPLClient, Snapshot
from .model import Prediction


def filter_rankings(
    predictions: Iterable[Prediction],
    *,
    position: str | None = None,
    max_price: float | None = None,
    max_ownership: float | None = None,
    min_minutes: float = 0.0,
    limit: int = 20,
) -> list[Prediction]:
    if limit < 1:
        raise ValueError("limit must be positive")
    normalized_position = position.upper() if position else None
    rows = [
        row
        for row in predictions
        if (normalized_position is None or row.position == normalized_position)
        and (max_price is None or row.price <= max_price)
        and (max_ownership is None or row.ownership_percent <= max_ownership)
        and row.expected_minutes >= min_minutes
    ]
    return rows[:limit]


def build_report(snapshot: Snapshot, predictions: list[Prediction], limit: int = 10) -> dict[str, Any]:
    if not predictions:
        raise ValueError("Prediction list is empty")
    event_id = predictions[0].target_event
    event = snapshot.event(event_id)
    captain_pool = [row for row in predictions if row.expected_minutes >= 55 and row.risk <= 0.45]
    captains = sorted(
        captain_pool,
        key=lambda row: row.expected_points * (1.0 - 0.30 * row.risk)
        + 0.45 * (row.expected_goals + row.expected_assists),
        reverse=True,
    )[:limit]
    differentials = sorted(
        [
            row
            for row in predictions
            if row.ownership_percent <= 10 and row.expected_minutes >= 50 and row.fixture_count
        ],
        key=lambda row: row.differential_score,
        reverse=True,
    )[:limit]
    value = sorted(
        [row for row in predictions if row.expected_minutes >= 50 and row.fixture_count],
        key=lambda row: row.value_score,
        reverse=True,
    )[:limit]
    market = sorted(
        [row for row in predictions if row.expected_minutes >= 30],
        key=lambda row: (row.market_net_transfers, row.market_momentum_percent),
        reverse=True,
    )[:limit]
    warnings: list[str] = []
    current = next((row for row in snapshot.bootstrap["events"] if row.get("is_current")), None)
    if current and not current.get("finished"):
        warnings.append(
            f"GW{current['id']} is not final; observed season totals can still change after Opta review."
        )
    if all(row.confidence == "low" for row in predictions[:limit]):
        warnings.append(
            "All leading predictions are low-confidence because the current-season sample is small."
        )
    return {
        "metadata": {
            "target_event": event_id,
            "deadline_utc": event.get("deadline_time"),
            "data_as_of": snapshot.fetched_at.isoformat(),
            "source_hash": snapshot.source_hash,
            "model_version": predictions[0].model_version,
            "player_count": len(predictions),
            "fixture_count": sum(1 for row in snapshot.fixtures if row.get("event") == event_id),
            "classification": {
                "observed": "official FPL public endpoint snapshot",
                "third_party": "FPL-provided team strength ratings",
                "calculated": "rank, value, differential, market momentum and risk",
                "prediction": "versioned expected minutes and points",
                "assumptions": "documented early-season priors and Poisson score model",
            },
        },
        "warnings": warnings,
        "rankings": [row.to_dict() for row in predictions[:limit]],
        "captains": [row.to_dict() for row in captains],
        "differentials": [row.to_dict() for row in differentials],
        "value": [row.to_dict() for row in value],
        "market": [row.to_dict() for row in market],
    }


def latest_public_picks_event(snapshot: Snapshot) -> int:
    now = datetime.now(timezone.utc)
    eligible: list[int] = []
    for event in snapshot.bootstrap["events"]:
        deadline = event.get("deadline_time")
        if not deadline:
            continue
        observed = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        if observed <= now:
            eligible.append(int(event["id"]))
    if not eligible:
        raise ValueError("No gameweek has passed its deadline, so manager picks are not public yet")
    return max(eligible)


def analyze_manager(
    client: FPLClient,
    snapshot: Snapshot,
    predictions: list[Prediction],
    entry_id: int,
    picks_event: int | None = None,
) -> dict[str, Any]:
    if not predictions:
        raise ValueError("Prediction list is empty")
    public_event = picks_event or latest_public_picks_event(snapshot)
    entry = client.entry(entry_id)
    history = client.entry_history(entry_id)
    picks_payload = client.entry_picks(entry_id, public_event)
    by_player = {row.player_id: row for row in predictions}
    picks: list[dict[str, Any]] = []
    projected_total = 0.0
    projected_starting = 0.0
    for pick in picks_payload.get("picks", []):
        prediction = by_player.get(int(pick["element"]))
        if prediction is None:
            continue
        multiplier = int(pick.get("multiplier") or 0)
        projected_total += prediction.expected_points * multiplier
        if int(pick["position"]) <= 11:
            projected_starting += prediction.expected_points
        picks.append(
            {
                "player_id": prediction.player_id,
                "name": prediction.player_name,
                "team": prediction.team,
                "position": prediction.position,
                "squad_slot": int(pick["position"]),
                "is_captain": bool(pick.get("is_captain")),
                "is_vice_captain": bool(pick.get("is_vice_captain")),
                "multiplier": multiplier,
                "expected_points": prediction.expected_points,
                "expected_minutes": prediction.expected_minutes,
                "risk": prediction.risk,
            }
        )
    starters = [row for row in picks if row["squad_slot"] <= 11]
    captain_candidates = sorted(
        [row for row in starters if row["expected_minutes"] >= 50],
        key=lambda row: (row["expected_points"], -row["risk"]),
        reverse=True,
    )
    weak_starters = sorted(starters, key=lambda row: (row["expected_points"], -row["risk"]))[:3]
    squad_ids = {row["player_id"] for row in picks}
    transfer_watchlist = [
        row.to_dict()
        for row in predictions
        if row.player_id not in squad_ids
        and row.expected_minutes >= 55
        and row.risk <= 0.45
    ][:8]
    overall_rank = entry.get("summary_overall_rank")
    total_players = snapshot.bootstrap.get("total_players")
    rank_percentile = None
    if overall_rank and total_players:
        rank_percentile = 100.0 * int(overall_rank) / int(total_players)
    current_history = history.get("current", [])
    return {
        "metadata": {
            "entry_id": int(entry_id),
            "team_name": entry.get("name"),
            "manager_name": " ".join(
                value for value in (entry.get("player_first_name"), entry.get("player_last_name")) if value
            ),
            "picks_observed_event": public_event,
            "prediction_target_event": predictions[0].target_event,
            "data_as_of": snapshot.fetched_at.isoformat(),
            "model_version": predictions[0].model_version,
        },
        "manager_strength": {
            "overall_rank": overall_rank,
            "overall_rank_percentile": round(rank_percentile, 3) if rank_percentile else None,
            "total_points": entry.get("summary_overall_points"),
            "gameweeks_observed": len(current_history),
            "strong_manager_flag": bool(rank_percentile is not None and rank_percentile <= 1.0),
            "classification": "calculated from observed public entry rank; not a skill causal estimate",
        },
        "squad_projection": {
            "starting_xp_before_captain": round(projected_starting, 3),
            "lineup_xp_with_current_multipliers": round(projected_total, 3),
            "recommended_captain": captain_candidates[0] if captain_candidates else None,
            "weakest_starters": weak_starters,
        },
        "picks": picks,
        "transfer_watchlist": transfer_watchlist,
        "limitations": [
            "Latest public picks are used; unconfirmed transfers after that deadline are unknowable.",
            "The watchlist is not yet a budget-, club-limit-, or multi-week-constrained optimizer.",
        ],
    }


def analyze_manager_cohort(
    client: FPLClient,
    snapshot: Snapshot,
    predictions: list[Prediction],
    *,
    league_id: int = 321,
    sample_size: int = 25,
    picks_event: int | None = None,
) -> dict[str, Any]:
    if not 1 <= sample_size <= 100:
        raise ValueError("sample_size must be between 1 and 100")
    public_event = picks_event or latest_public_picks_event(snapshot)
    standings_rows: list[dict[str, Any]] = []
    page = 1
    league_name = None
    while len(standings_rows) < sample_size:
        payload = client.classic_league_standings(league_id, page)
        league_name = payload.get("league", {}).get("name") or league_name
        results = payload.get("standings", {}).get("results", [])
        if not results:
            break
        standings_rows.extend(results)
        if not payload.get("standings", {}).get("has_next"):
            break
        page += 1
    cohort = standings_rows[:sample_size]
    if not cohort:
        raise ValueError(f"Classic league {league_id} returned no public managers")
    prediction_by_player = {row.player_id: row for row in predictions}
    player_counts: dict[int, int] = {}
    captain_counts: dict[int, int] = {}
    successful_entries: list[int] = []
    failures: list[dict[str, Any]] = []
    for manager in cohort:
        entry_id = int(manager["entry"])
        try:
            picks = client.entry_picks(entry_id, public_event).get("picks", [])
        except Exception as exc:
            failures.append({"entry_id": entry_id, "error": type(exc).__name__})
            continue
        successful_entries.append(entry_id)
        for pick in picks:
            player_id = int(pick["element"])
            player_counts[player_id] = player_counts.get(player_id, 0) + 1
            if pick.get("is_captain"):
                captain_counts[player_id] = captain_counts.get(player_id, 0) + 1

    denominator = len(successful_entries)
    if denominator == 0:
        raise ValueError("No manager picks in the cohort could be read")

    def consensus_row(item: tuple[int, int], captain: bool = False) -> dict[str, Any]:
        player_id, count = item
        prediction = prediction_by_player.get(player_id)
        return {
            "player_id": player_id,
            "name": prediction.player_name if prediction else None,
            "team": prediction.team if prediction else None,
            "selection_count" if not captain else "captain_count": count,
            "cohort_percent": round(100.0 * count / denominator, 2),
            "next_event_xp": prediction.expected_points if prediction else None,
            "next_event_risk": prediction.risk if prediction else None,
        }

    selection_consensus = [
        consensus_row(item)
        for item in sorted(player_counts.items(), key=lambda item: item[1], reverse=True)[:20]
    ]
    captain_consensus = [
        consensus_row(item, captain=True)
        for item in sorted(captain_counts.items(), key=lambda item: item[1], reverse=True)[:10]
    ]
    return {
        "metadata": {
            "league_id": league_id,
            "league_name": league_name,
            "requested_sample": sample_size,
            "successful_sample": denominator,
            "picks_observed_event": public_event,
            "prediction_target_event": predictions[0].target_event,
            "data_as_of": snapshot.fetched_at.isoformat(),
        },
        "selection_consensus": selection_consensus,
        "captain_consensus": captain_consensus,
        "failures": failures,
        "limitations": [
            "This is descriptive consensus, not evidence that copying the cohort improves rank.",
            "The default cohort qualified through prior-season top-1% performance and is survivorship-selected.",
            "Small samples are unstable; expand only while respecting the public API.",
        ],
    }
