"""Evaluate role-prior decay for transfers, promotion, and other pre-season transitions."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .benchmark import SeasonArchive, _metric_row
from .component_history import component_history_prior
from .historical import build_season_evidence
from .history_benchmark import _average_metric_rows
from .role_transition import (
    RoleTransitionExpectedPointsModel,
    transition_profiles,
    transition_role_weights,
)


def _summary(
    metric_rows: list[dict[str, float]],
    minute_errors: list[float],
    minute_biases: list[float],
    risks: list[float],
    count: int,
) -> dict[str, float | int]:
    result: dict[str, float | int] = {
        **_average_metric_rows(metric_rows),
        "rows": count,
    }
    if minute_errors:
        result["minutes_mae"] = round(mean(minute_errors), 6)
        result["minutes_bias"] = round(mean(minute_biases), 6)
    if risks:
        result["mean_reported_risk"] = round(mean(risks), 6)
    return result


def benchmark_transition_weight(
    archive: SeasonArchive,
    priors: dict[str, Any],
    profiles: dict[int, Any],
    *,
    transition_weight: float,
    first_event: int = 1,
    last_event: int = 10,
) -> dict[str, Any]:
    weights = transition_role_weights(profiles, transition_weight=transition_weight)
    event_metrics: dict[str, dict[str, list[dict[str, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    minute_errors: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    minute_biases: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    risks: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for event in range(first_event, last_event + 1):
        snapshot = archive.snapshot_before(event)
        model = RoleTransitionExpectedPointsModel(
            priors=priors,
            role_weights=weights,
            model_version=f"xp-v0.3-transition-role-{transition_weight:.2f}",
        )
        predicted = {row.player_code: row for row in model.predict(snapshot, event)}
        actuals_by_id = archive.actuals(event)
        actuals = {
            archive.id_to_code[player_id]: actual
            for player_id, actual in actuals_by_id.items()
            if player_id in archive.id_to_code
        }

        cohort_event_rows: dict[str, dict[str, list[tuple[Any, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for code, actual in actuals.items():
            prediction = predicted.get(code)
            profile = profiles.get(code)
            if prediction is None or profile is None:
                continue
            for label in profile.labels():
                cohort_event_rows[label]["all"].append((prediction, actual))
                if actual.starts > 0:
                    cohort_event_rows[label]["starters"].append((prediction, actual))

        for label, populations in cohort_event_rows.items():
            for population, rows in populations.items():
                if not rows:
                    continue
                estimates = [prediction.expected_points for prediction, _ in rows]
                observed = [actual.points for _, actual in rows]
                intervals = [
                    (prediction.lower_bound, prediction.upper_bound)
                    for prediction, _ in rows
                ]
                event_metrics[label][population].append(
                    _metric_row(estimates, observed, intervals)
                )
                for prediction, actual in rows:
                    minute_errors[label][population].append(
                        abs(prediction.expected_minutes - actual.minutes)
                    )
                    minute_biases[label][population].append(
                        prediction.expected_minutes - actual.minutes
                    )
                    risks[label][population].append(prediction.risk)
                counts[label][population] += len(rows)

    cohorts: dict[str, Any] = {}
    for label in sorted(event_metrics):
        cohorts[label] = {
            population: _summary(
                event_metrics[label][population],
                minute_errors[label][population],
                minute_biases[label][population],
                risks[label][population],
                counts[label][population],
            )
            for population in ("all", "starters")
            if event_metrics[label][population]
        }

    return {
        "transition_weight": transition_weight,
        "events": [first_event, last_event],
        "weighted_players": len(weights),
        "cohorts": cohorts,
    }


def run_role_transition_experiment(
    data_root: Path,
    *,
    target_season: str = "2025-26",
    prior_seasons: Iterable[str],
    transition_weights: tuple[float, ...] = (1.0, 0.75, 0.5, 0.25, 0.0),
    first_event: int = 1,
    last_event: int = 10,
) -> dict[str, Any]:
    prior_names = list(prior_seasons)
    target_start = int(target_season.split("-", 1)[0])
    invalid = [name for name in prior_names if int(name.split("-", 1)[0]) >= target_start]
    if invalid:
        raise ValueError(f"Prior seasons must precede {target_season}: {invalid}")
    if not prior_names:
        raise ValueError("At least one prior season is required")

    evidence = [build_season_evidence(data_root / season, season) for season in prior_names]
    # Use the best component-memory development profile found in the preceding experiment.
    # This is still a challenger, not a production promotion.
    priors = component_history_prior(
        evidence,
        role_window=1,
        attack_window=3,
        ancillary_window=3,
        dc_window=1,
    )
    archive = SeasonArchive(data_root / target_season)
    latest_prior_season = max(prior_names, key=lambda name: int(name.split("-", 1)[0]))
    profiles = transition_profiles(
        archive,
        priors,
        data_root / latest_prior_season,
    )
    profile_counts: dict[str, int] = defaultdict(int)
    for profile in profiles.values():
        for label in profile.labels():
            profile_counts[label] += 1

    candidates = {
        f"weight_{weight:.2f}": benchmark_transition_weight(
            archive,
            priors,
            profiles,
            transition_weight=weight,
            first_event=first_event,
            last_event=last_event,
        )
        for weight in transition_weights
    }

    leaderboard = []
    for label, result in candidates.items():
        all_starters = result["cohorts"].get("all", {}).get("starters", {})
        transition_all = result["cohorts"].get("role_transition", {}).get("all", {})
        transition_starters = result["cohorts"].get("role_transition", {}).get(
            "starters", {}
        )
        leaderboard.append(
            {
                "label": label,
                "transition_weight": result["transition_weight"],
                "all_starter_ndcg_at_10": all_starters.get("ndcg_at_10"),
                "all_starter_points_mae": all_starters.get("mae"),
                "transition_points_mae": transition_all.get("mae"),
                "transition_minutes_mae": transition_all.get("minutes_mae"),
                "transition_starter_points_mae": transition_starters.get("mae"),
                "transition_starter_minutes_mae": transition_starters.get("minutes_mae"),
                "transition_interval_coverage": transition_all.get("interval_coverage"),
                "transition_mean_reported_risk": transition_all.get("mean_reported_risk"),
            }
        )

    leaderboard.sort(
        key=lambda row: (
            -(row["transition_minutes_mae"] if row["transition_minutes_mae"] is not None else 999),
            row["all_starter_ndcg_at_10"] or 0.0,
            -(row["transition_points_mae"] if row["transition_points_mae"] is not None else 999),
        ),
        reverse=True,
    )

    return {
        "experiment": "role-transition-prior-decay-v0.3",
        "target_season": target_season,
        "prior_seasons_available": prior_names,
        "events": [first_event, last_event],
        "profile_counts": dict(sorted(profile_counts.items())),
        "leaderboard": leaderboard,
        "candidates": candidates,
    }
