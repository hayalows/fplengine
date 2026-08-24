"""Evaluate upper-tail interval inflation on held-out gameweeks.

Every candidate shares identical means by construction, so the leaderboard isolates
the coverage/width trade-off. Metrics are computed per gameweek and averaged,
matching the other research benchmarks.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .benchmark import SeasonArchive, _metric_row
from .component_history import component_history_prior
from .historical import build_season_evidence
from .history_benchmark import _average_metric_rows
from .role_transition import TransitionProfile, transition_profiles
from .transition_uncertainty import (
    IntervalCalibrationExpectedPointsModel,
    compose_upper_multipliers,
)


def _interval_row(
    estimates: list[float],
    observed: list[float],
    intervals: list[tuple[float, float]],
) -> dict[str, float]:
    metrics = _metric_row(estimates, observed, intervals)
    above = [1.0 if actual > upper else 0.0 for (_, upper), actual in zip(intervals, observed)]
    below = [1.0 if actual < lower else 0.0 for (lower, _), actual in zip(intervals, observed)]
    metrics["frac_above_upper"] = round(sum(above) / len(above), 6)
    metrics["frac_below_lower"] = round(sum(below) / len(below), 6)
    return metrics


def benchmark_interval_candidate(
    archive: SeasonArchive,
    priors: dict[str, Any],
    profiles: dict[int, TransitionProfile],
    *,
    global_factor: float,
    scope: str,
    transition_extra: float,
    first_event: int = 1,
    last_event: int = 10,
) -> dict[str, Any]:
    multipliers_by_code = compose_upper_multipliers(
        profiles,
        scope=scope,
        factor=transition_extra,
        global_factor=global_factor,
    )
    per_event: dict[str, dict[str, list[dict[str, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for event in range(first_event, last_event + 1):
        snapshot = archive.snapshot_before(event)
        model = IntervalCalibrationExpectedPointsModel(
            priors=priors,
            upper_multipliers=multipliers_by_code,
        )
        predicted = {row.player_code: row for row in model.predict(snapshot, event)}
        actuals = {
            archive.id_to_code[player_id]: actual
            for player_id, actual in archive.actuals(event).items()
            if player_id in archive.id_to_code
        }
        cohort_rows: dict[str, list[tuple[Any, Any]]] = defaultdict(list)
        for code, actual in actuals.items():
            prediction = predicted.get(code)
            profile = profiles.get(code)
            if prediction is None or profile is None:
                continue
            for label in profile.labels():
                cohort_rows[label].append((prediction, actual))

        for label, rows in cohort_rows.items():
            if not rows:
                continue
            per_event[label]["all"].append(
                _interval_row(
                    [prediction.expected_points for prediction, _ in rows],
                    [actual.points for _, actual in rows],
                    [
                        (prediction.lower_bound, prediction.upper_bound)
                        for prediction, _ in rows
                    ],
                )
            )
            starter_rows = [row for row in rows if row[1].starts > 0]
            if starter_rows:
                per_event[label]["starters"].append(
                    _interval_row(
                        [prediction.expected_points for prediction, _ in starter_rows],
                        [actual.points for _, actual in starter_rows],
                        [
                            (prediction.lower_bound, prediction.upper_bound)
                            for prediction, _ in starter_rows
                        ],
                    )
                )
            counts[label]["all"] += len(rows)
            counts[label]["starters"] += len(starter_rows)

    cohorts: dict[str, Any] = {}
    for label, populations in sorted(per_event.items()):
        cohorts[label] = {}
        for population, rows in populations.items():
            metrics = _average_metric_rows(rows)
            metrics["rows"] = counts[label][population]
            cohorts[label][population] = metrics
    return {
        "global_factor": global_factor,
        "scope": scope,
        "transition_extra": transition_extra,
        "cohorts": cohorts,
    }


def run_interval_calibration_experiment(
    data_root: Path,
    *,
    target_season: str,
    prior_seasons: Iterable[str],
    global_factors: tuple[float, ...] = (1.0, 1.25, 1.5, 2.0),
    scopes: tuple[str, ...] = ("none",),
    transition_extras: tuple[float, ...] = (1.0,),
    first_event: int = 1,
    last_event: int = 10,
    target_starter_coverage: float = 0.85,
) -> dict[str, Any]:
    prior_names = list(prior_seasons)
    target_start = int(target_season.split("-", 1)[0])
    invalid = [name for name in prior_names if int(name.split("-", 1)[0]) >= target_start]
    if invalid:
        raise ValueError(f"Prior seasons must precede {target_season}: {invalid}")
    if not prior_names:
        raise ValueError("At least one prior season is required")

    evidence = [build_season_evidence(data_root / season, season) for season in prior_names]
    # Same development prior profile as the role-transition experiments so results stay
    # comparable across the v0.3 research line.
    priors = component_history_prior(
        evidence,
        role_window=1,
        attack_window=3,
        ancillary_window=3,
        dc_window=1,
    )
    archive = SeasonArchive(data_root / target_season)
    latest_prior = max(prior_names, key=lambda name: int(name.split("-", 1)[0]))
    profiles = transition_profiles(archive, priors, data_root / latest_prior)

    candidates: dict[str, Any] = {}
    for global_factor in global_factors:
        for scope in scopes:
            for extra in transition_extras:
                label = f"upper{global_factor:.2f}_{scope}_extra{extra:.2f}"
                candidates[label] = benchmark_interval_candidate(
                    archive,
                    priors,
                    profiles,
                    global_factor=global_factor,
                    scope=scope,
                    transition_extra=extra,
                    first_event=first_event,
                    last_event=last_event,
                )

    leaderboard = []
    for label, result in candidates.items():
        starters = result["cohorts"].get("all", {}).get("starters", {})
        everyone = result["cohorts"].get("all", {}).get("all", {})
        coverage = starters.get("interval_coverage")
        leaderboard.append(
            {
                "label": label,
                "global_factor": result["global_factor"],
                "scope": result["scope"],
                "transition_extra": result["transition_extra"],
                "starter_coverage": coverage,
                "starter_mean_interval_width": starters.get("mean_interval_width"),
                "all_coverage": everyone.get("interval_coverage"),
                "starter_ndcg_at_10": starters.get("ndcg_at_10"),
                "starter_mae": starters.get("mae"),
                "starter_frac_above_upper": starters.get("frac_above_upper"),
                "starter_frac_below_lower": starters.get("frac_below_lower"),
                "coverage_distance_from_target": (
                    round(abs(coverage - target_starter_coverage), 6)
                    if coverage is not None
                    else None
                ),
            }
        )
    leaderboard.sort(
        key=lambda row: (
            row["coverage_distance_from_target"]
            if row["coverage_distance_from_target"] is not None
            else 999.0,
            row["starter_mean_interval_width"] or 999.0,
        )
    )
    return {
        "experiment": "interval-calibration-v0.3",
        "target_season": target_season,
        "prior_seasons_available": prior_names,
        "events": [first_event, last_event],
        "target_starter_coverage": target_starter_coverage,
        "leaderboard": leaderboard,
        "candidates": candidates,
    }
