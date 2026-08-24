"""Benchmark schema-aware historical priors on held-out FPL gameweeks."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .benchmark import SeasonArchive, _metric_row
from .historical import build_season_evidence, history_window_variants
from .historical_model import HistoricalExpectedPointsModel


def _average_metric_rows(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    keys = sorted({key for row in rows for key in row})
    return {
        key: round(mean(row[key] for row in rows if key in row), 6)
        for key in keys
    }


def _top10_actual_mean(predicted: list[float], actual: list[float]) -> float:
    if not predicted:
        return 0.0
    order = sorted(range(len(predicted)), key=predicted.__getitem__, reverse=True)[:10]
    return mean(actual[index] for index in order) if order else 0.0


def benchmark_history_candidate(
    archive: SeasonArchive,
    priors: dict[str, Any],
    *,
    first_event: int = 6,
    last_event: int = 38,
    label: str = "history_challenger",
) -> dict[str, Any]:
    """Score one historical-prior candidate gameweek by gameweek.

    Ranking metrics are calculated within each gameweek and then averaged. This avoids
    the invalid shortcut of ranking player-gameweeks from different deadlines together.
    """
    per_population: dict[str, list[dict[str, float]]] = defaultdict(list)
    top10_points: dict[str, list[float]] = defaultdict(list)
    row_counts = {"all": 0, "starters": 0}

    for event in range(first_event, last_event + 1):
        snapshot = archive.snapshot_before(event)
        predictions = HistoricalExpectedPointsModel(
            priors=priors,
            model_version=f"xp-v0.3-{label}",
        ).predict(snapshot, event)
        predicted = {row.player_id: row for row in predictions}
        actuals = archive.actuals(event)

        for population in ("all", "starters"):
            ids = [
                player_id
                for player_id, actual in actuals.items()
                if player_id in predicted and (population == "all" or actual.starts > 0)
            ]
            if not ids:
                continue
            estimates = [predicted[player_id].expected_points for player_id in ids]
            observed = [actuals[player_id].points for player_id in ids]
            intervals = [
                (predicted[player_id].lower_bound, predicted[player_id].upper_bound)
                for player_id in ids
            ]
            per_population[population].append(_metric_row(estimates, observed, intervals))
            top10_points[population].append(_top10_actual_mean(estimates, observed))
            row_counts[population] += len(ids)

    metrics = {
        population: {
            **_average_metric_rows(per_population[population]),
            "top10_actual_mean": round(mean(top10_points[population]), 6)
            if top10_points[population]
            else 0.0,
        }
        for population in ("all", "starters")
    }
    return {
        "label": label,
        "source_seasons": priors.get("source_seasons", []),
        "decay": priors.get("decay"),
        "events": [first_event, last_event],
        "rows": row_counts,
        "metrics": metrics,
    }


def benchmark_simple_baselines(
    archive: SeasonArchive,
    *,
    first_event: int = 6,
    last_event: int = 38,
) -> dict[str, Any]:
    """Aggregate simple decision baselines over the same held-out gameweeks."""
    rows: dict[str, dict[str, list[dict[str, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    top10: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for event in range(first_event, last_event + 1):
        actuals = archive.actuals(event)
        baselines = archive.simple_baselines(event)
        for model_name, estimates_by_id in baselines.items():
            # Archive FPL xP timing is not verified as pre-deadline, so it is kept out of
            # the model-selection table even though SeasonArchive exposes it for research.
            if model_name == "archive_fpl_xp_timing_unverified":
                continue
            for population in ("all", "starters"):
                ids = [
                    player_id
                    for player_id, actual in actuals.items()
                    if player_id in estimates_by_id
                    and (population == "all" or actual.starts > 0)
                ]
                if not ids:
                    continue
                estimates = [estimates_by_id[player_id] for player_id in ids]
                observed = [actuals[player_id].points for player_id in ids]
                rows[model_name][population].append(_metric_row(estimates, observed))
                top10[model_name][population].append(_top10_actual_mean(estimates, observed))
                counts[model_name][population] += len(ids)

    return {
        model_name: {
            population: {
                **_average_metric_rows(rows[model_name][population]),
                "top10_actual_mean": round(mean(top10[model_name][population]), 6)
                if top10[model_name][population]
                else 0.0,
                "rows": counts[model_name][population],
            }
            for population in ("all", "starters")
        }
        for model_name in sorted(rows)
    }


def run_history_depth_experiment(
    data_root: Path,
    *,
    target_season: str,
    prior_seasons: Iterable[str],
    windows: tuple[int, ...] = (1, 2, 3, 5, 7, 10),
    decays: tuple[float, ...] = (1.0, 0.85, 0.70),
    first_event: int = 6,
    last_event: int = 38,
) -> dict[str, Any]:
    """Build historical candidates from seasons strictly before the target season."""
    prior_names = list(prior_seasons)
    target_start = int(target_season.split("-", 1)[0])
    invalid = [name for name in prior_names if int(name.split("-", 1)[0]) >= target_start]
    if invalid:
        raise ValueError(f"Prior seasons must precede {target_season}: {invalid}")

    evidence = [build_season_evidence(data_root / season, season) for season in prior_names]
    variants = history_window_variants(evidence, windows=windows, decays=decays)
    archive = SeasonArchive(data_root / target_season)

    candidates: dict[str, Any] = {}
    for label, priors in variants.items():
        candidates[label] = benchmark_history_candidate(
            archive,
            priors,
            first_event=first_event,
            last_event=last_event,
            label=label,
        )

    def starter_key(item: tuple[str, dict[str, Any]]) -> tuple[float, float, float]:
        metrics = item[1]["metrics"]["starters"]
        # Decision-facing ranking first, then numerical accuracy, then top-list returns.
        return (
            metrics.get("ndcg_at_10", 0.0),
            -metrics.get("mae", 999.0),
            metrics.get("top10_actual_mean", 0.0),
        )

    leaderboard = [
        {
            "label": label,
            "source_seasons": result["source_seasons"],
            "decay": result["decay"],
            "starter_mae": result["metrics"]["starters"].get("mae"),
            "starter_ndcg_at_10": result["metrics"]["starters"].get("ndcg_at_10"),
            "starter_top10_actual_mean": result["metrics"]["starters"].get(
                "top10_actual_mean"
            ),
            "all_mae": result["metrics"]["all"].get("mae"),
            "all_ndcg_at_10": result["metrics"]["all"].get("ndcg_at_10"),
        }
        for label, result in sorted(candidates.items(), key=starter_key, reverse=True)
    ]

    return {
        "experiment": "schema-aware-history-depth-v0.3",
        "target_season": target_season,
        "prior_seasons_available": prior_names,
        "ruleset_note": (
            "Total-FPL-point model selection is scoped to the 2025/26 target because "
            "defensive-contribution points began that season; older seasons remain useful "
            "as field-specific football/role evidence only."
        ),
        "first_event": first_event,
        "last_event": last_event,
        "simple_baselines": benchmark_simple_baselines(
            archive, first_event=first_event, last_event=last_event
        ),
        "leaderboard": leaderboard,
        "candidates": candidates,
    }
