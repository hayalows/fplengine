"""Grid-search role decay separately for club changes and promoted-team context."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .benchmark import SeasonArchive, _metric_row
from .component_history import component_history_prior
from .historical import build_season_evidence
from .history_benchmark import _average_metric_rows, _top10_actual_mean
from .role_transition import (
    RoleTransitionExpectedPointsModel,
    TransitionProfile,
    transition_profiles,
)


def split_role_weights(
    profiles: dict[int, TransitionProfile],
    *,
    club_change_weight: float,
    promoted_weight: float,
) -> dict[int, float]:
    """Compose independent role-retention multipliers per player.

    Club change and promoted-team context multiply rather than take a minimum. This
    keeps both axes identifiable: with a one-season role window, every promoted-team
    player carrying role evidence necessarily changed club too, so ``min`` collapsed
    large parts of the grid into duplicate candidates. Multiplication reads naturally
    as two independent hazards on role persistence, and a promoted weight of 1.0
    leaves plain club-change behaviour unchanged.
    """
    if not 0.0 <= club_change_weight <= 1.0 or not 0.0 <= promoted_weight <= 1.0:
        raise ValueError("transition weights must be in [0, 1]")
    result: dict[int, float] = {}
    for code, profile in profiles.items():
        weight = 1.0
        if profile.club_change:
            weight *= club_change_weight
        if profile.promoted_team:
            weight *= promoted_weight
        if weight != 1.0:
            result[code] = weight
    return result


def split_cohort_labels(profile: TransitionProfile) -> tuple[str, ...]:
    """Cohort labels that separate transfers into promoted clubs from other transfers."""
    labels = ["all"]
    if profile.same_club:
        labels.append("same_club")
    if profile.club_change:
        labels.append("club_change")
        labels.append(
            "transfer_to_promoted" if profile.promoted_team else "transfer_established"
        )
    if profile.new_to_fpl:
        labels.append("new_to_fpl")
    if profile.promoted_team:
        labels.append("promoted_team")
    if profile.transition:
        labels.append("role_transition")
    else:
        labels.append("no_transition")
    return tuple(labels)


def profile_signature(profile: TransitionProfile) -> str:
    parts = []
    if profile.same_club:
        parts.append("same_club")
    if profile.club_change:
        parts.append("club_change")
    if profile.new_to_fpl:
        parts.append("new_to_fpl")
    if profile.promoted_team:
        parts.append("promoted_team")
    return "+".join(parts) if parts else "no_preseason_transition"


def _evaluate_weight_map(
    archive: SeasonArchive,
    priors: dict[str, Any],
    profiles: dict[int, TransitionProfile],
    role_weights: dict[int, float],
    *,
    first_event: int,
    last_event: int,
) -> dict[str, Any]:
    per_event: dict[str, dict[str, list[dict[str, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    minute_errors: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    minute_biases: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for event in range(first_event, last_event + 1):
        snapshot = archive.snapshot_before(event)
        model = RoleTransitionExpectedPointsModel(
            priors=priors,
            role_weights=role_weights,
            model_version="xp-v0.3-split-transition-challenger",
        )
        predictions = {row.player_code: row for row in model.predict(snapshot, event)}
        actuals = {
            archive.id_to_code[player_id]: actual
            for player_id, actual in archive.actuals(event).items()
            if player_id in archive.id_to_code
        }
        event_rows: dict[str, dict[str, list[tuple[Any, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for code, actual in actuals.items():
            prediction = predictions.get(code)
            profile = profiles.get(code)
            if prediction is None or profile is None:
                continue
            for cohort in split_cohort_labels(profile):
                event_rows[cohort]["all"].append((prediction, actual))
                if actual.starts > 0:
                    event_rows[cohort]["starters"].append((prediction, actual))

        for cohort, populations in event_rows.items():
            for population, rows in populations.items():
                if not rows:
                    continue
                metrics = _metric_row(
                    [prediction.expected_points for prediction, _ in rows],
                    [actual.points for _, actual in rows],
                    [
                        (prediction.lower_bound, prediction.upper_bound)
                        for prediction, _ in rows
                    ],
                )
                if len(rows) >= 10:
                    metrics["top10_actual_mean"] = _top10_actual_mean(
                        [prediction.expected_points for prediction, _ in rows],
                        [actual.points for _, actual in rows],
                    )
                per_event[cohort][population].append(metrics)
                for prediction, actual in rows:
                    minute_errors[cohort][population].append(
                        abs(prediction.expected_minutes - actual.minutes)
                    )
                    minute_biases[cohort][population].append(
                        prediction.expected_minutes - actual.minutes
                    )
                counts[cohort][population] += len(rows)

    cohorts: dict[str, Any] = {}
    for cohort, populations in per_event.items():
        cohorts[cohort] = {}
        for population, rows in populations.items():
            metrics = _average_metric_rows(rows)
            errors = minute_errors[cohort][population]
            biases = minute_biases[cohort][population]
            if errors:
                metrics["minutes_mae"] = round(sum(errors) / len(errors), 6)
            if biases:
                metrics["minutes_bias"] = round(sum(biases) / len(biases), 6)
            metrics["rows"] = counts[cohort][population]
            cohorts[cohort][population] = metrics
    return cohorts


def run_split_transition_experiment(
    data_root: Path,
    *,
    target_season: str,
    prior_seasons: Iterable[str],
    club_weights: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0),
    promoted_weights: tuple[float, ...] = (0.0, 0.5, 1.0),
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
    signature_counts: dict[str, int] = defaultdict(int)
    for profile in profiles.values():
        signature_counts[profile_signature(profile)] += 1

    candidates: dict[str, Any] = {}
    for club_weight in club_weights:
        for promoted_weight in promoted_weights:
            label = f"club{club_weight:.2f}_promoted{promoted_weight:.2f}"
            weights = split_role_weights(
                profiles,
                club_change_weight=club_weight,
                promoted_weight=promoted_weight,
            )
            cohorts = _evaluate_weight_map(
                archive,
                priors,
                profiles,
                weights,
                first_event=first_event,
                last_event=last_event,
            )
            candidates[label] = {
                "club_change_weight": club_weight,
                "promoted_weight": promoted_weight,
                "cohorts": cohorts,
            }

    leaderboard = []
    for label, result in candidates.items():
        all_starters = result["cohorts"].get("all", {}).get("starters", {})
        club = result["cohorts"].get("club_change", {}).get("all", {})
        established = result["cohorts"].get("transfer_established", {}).get("all", {})
        to_promoted = result["cohorts"].get("transfer_to_promoted", {}).get("all", {})
        promoted = result["cohorts"].get("promoted_team", {}).get("all", {})
        leaderboard.append(
            {
                "label": label,
                "club_change_weight": result["club_change_weight"],
                "promoted_weight": result["promoted_weight"],
                "all_starter_ndcg_at_10": all_starters.get("ndcg_at_10"),
                "all_starter_points_mae": all_starters.get("mae"),
                "club_minutes_mae": club.get("minutes_mae"),
                "club_points_mae": club.get("mae"),
                "club_interval_coverage": club.get("interval_coverage"),
                "transfer_established_minutes_mae": established.get("minutes_mae"),
                "transfer_established_points_mae": established.get("mae"),
                "transfer_to_promoted_minutes_mae": to_promoted.get("minutes_mae"),
                "transfer_to_promoted_points_mae": to_promoted.get("mae"),
                "promoted_minutes_mae": promoted.get("minutes_mae"),
                "promoted_points_mae": promoted.get("mae"),
            }
        )
    leaderboard.sort(
        key=lambda row: (
            row["all_starter_ndcg_at_10"] or 0.0,
            -(row["club_minutes_mae"] or 999.0),
            -(row["club_points_mae"] or 999.0),
        ),
        reverse=True,
    )
    return {
        "experiment": "split-transition-role-decay-v0.3",
        "target_season": target_season,
        "prior_seasons_available": prior_names,
        "events": [first_event, last_event],
        "profile_counts": dict(sorted(signature_counts.items())),
        "leaderboard": leaderboard,
        "candidates": candidates,
    }
