"""Reproducible historical-depth and role-transition experiment for v0.3."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from .benchmark import SeasonArchive, _metric_row
from .history import SeasonEvidence, build_season_evidence, merge_season_evidence
from .model import ExpectedPointsModel
from .model_v3 import ExpectedPointsModelV3
from .priors import build_prior_payload

SEASONS = [
    "2016-17",
    "2017-18",
    "2018-19",
    "2019-20",
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
    "2025-26",
]
TARGETS = ["2023-24", "2024-25", "2025-26"]
DEPTHS = [1, 2, 3, 5, 7, 10]
HALF_LIVES: list[float | None] = [None, 1.5, 3.0]
RETENTIONS = [1.0, 0.80, 0.65, 0.50]


def _aggregate(rows: list[dict[str, float]]) -> dict[str, float]:
    if not rows:
        return {}
    return {metric: round(mean(row[metric] for row in rows), 6) for metric in rows[0]}


def _evaluate(
    archive: SeasonArchive,
    model: Any,
    *,
    first_event: int = 6,
    last_event: int = 38,
) -> dict[str, Any]:
    metrics: dict[str, list[dict[str, float]]] = defaultdict(list)
    transition_metrics: dict[str, list[dict[str, float]]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    for event in range(first_event, last_event + 1):
        snapshot = archive.snapshot_before(event)
        predicted_rows = model.predict(snapshot, event)
        estimates = {row.player_id: row.expected_points for row in predicted_rows}
        intervals = {row.player_id: (row.lower_bound, row.upper_bound) for row in predicted_rows}
        actuals = archive.actuals(event)
        for cohort, keys in (
            ("all", list(actuals)),
            ("starters", [key for key, value in actuals.items() if value.starts > 0]),
        ):
            eligible = [key for key in keys if key in estimates]
            if not eligible:
                continue
            counts[cohort] += len(eligible)
            metrics[cohort].append(
                _metric_row(
                    [estimates[key] for key in eligible],
                    [actuals[key].points for key in eligible],
                    [intervals[key] for key in eligible],
                )
            )

        if isinstance(model, ExpectedPointsModelV3):
            player_rows = {int(row["id"]): row for row in snapshot.bootstrap["elements"]}
            for transition in ("continuity", "club_change", "promoted_or_new_team", "new_or_unmapped"):
                eligible = [
                    key
                    for key, actual in actuals.items()
                    if actual.starts > 0
                    and key in estimates
                    and key in player_rows
                    and model._transition_kind(player_rows[key]) == transition
                ]
                if not eligible:
                    continue
                counts[f"transition:{transition}"] += len(eligible)
                transition_metrics[transition].append(
                    _metric_row(
                        [estimates[key] for key in eligible],
                        [actuals[key].points for key in eligible],
                        [intervals[key] for key in eligible],
                    )
                )

    return {
        "cohorts": {name: _aggregate(rows) for name, rows in metrics.items()},
        "transitions": {name: _aggregate(rows) for name, rows in transition_metrics.items()},
        "row_counts": dict(counts),
        "gameweeks": last_event - first_event + 1,
    }


def _dev_score(result: dict[str, Any]) -> tuple[float, float, float]:
    starter = result["cohorts"].get("starters", {})
    return (
        float(starter.get("ndcg_at_10", 0.0)),
        float(starter.get("top_10_overlap", 0.0)),
        -float(starter.get("mae", 99.0)),
    )


def run_experiment(root: Path) -> dict[str, Any]:
    evidence: dict[str, SeasonEvidence] = {}
    for season in SEASONS:
        path = root / season
        if path.exists():
            evidence[season] = build_season_evidence(path, season)
    missing = [season for season in TARGETS if season not in evidence]
    if missing:
        raise ValueError(f"Missing target seasons: {missing}")

    # Stage 1: choose history depth/decay on 2023/24 and 2024/25 only.
    development_targets = ["2023-24", "2024-25"]
    depth_results: dict[str, Any] = {}
    for depth in DEPTHS:
        for half_life in HALF_LIVES:
            name = f"depth={depth};half_life={half_life}"
            season_rows: dict[str, Any] = {}
            for target in development_targets:
                target_index = SEASONS.index(target)
                training_names = [season for season in SEASONS[:target_index] if season in evidence]
                selected = [evidence[season] for season in training_names]
                priors = merge_season_evidence(
                    selected,
                    depth=min(depth, len(selected)),
                    half_life_seasons=half_life,
                )
                season_rows[target] = _evaluate(
                    SeasonArchive(root / target),
                    ExpectedPointsModelV3(priors=priors, transition_retention=1.0),
                )
            starter_rows = [row["cohorts"]["starters"] for row in season_rows.values()]
            aggregate = {
                metric: round(mean(row[metric] for row in starter_rows), 6)
                for metric in starter_rows[0]
            }
            depth_results[name] = {
                "depth": depth,
                "half_life": half_life,
                "development": season_rows,
                "development_starters": aggregate,
            }

    eligible_depths = sorted(
        depth_results.items(),
        key=lambda item: (
            item[1]["development_starters"]["ndcg_at_10"],
            item[1]["development_starters"]["top_10_overlap"],
            -item[1]["development_starters"]["mae"],
        ),
        reverse=True,
    )
    winning_depth_name, winning_depth = eligible_depths[0]

    # Stage 2: choose how much prior role evidence survives a team/role transition.
    transition_results: dict[str, Any] = {}
    for retention in RETENTIONS:
        season_rows: dict[str, Any] = {}
        for target in development_targets:
            target_index = SEASONS.index(target)
            training_names = [season for season in SEASONS[:target_index] if season in evidence]
            selected = [evidence[season] for season in training_names]
            priors = merge_season_evidence(
                selected,
                depth=min(winning_depth["depth"], len(selected)),
                half_life_seasons=winning_depth["half_life"],
            )
            season_rows[target] = _evaluate(
                SeasonArchive(root / target),
                ExpectedPointsModelV3(priors=priors, transition_retention=retention),
            )
        starter_rows = [row["cohorts"]["starters"] for row in season_rows.values()]
        aggregate = {
            metric: round(mean(row[metric] for row in starter_rows), 6)
            for metric in starter_rows[0]
        }
        transition_results[str(retention)] = {
            "retention": retention,
            "development": season_rows,
            "development_starters": aggregate,
        }
    winning_retention_key, winning_transition = max(
        transition_results.items(),
        key=lambda item: (
            item[1]["development_starters"]["ndcg_at_10"],
            item[1]["development_starters"]["top_10_overlap"],
            -item[1]["development_starters"]["mae"],
        ),
    )

    # Stage 3: validate the selected candidate on 2025/26 and compare with v0.2.
    validation_target = "2025-26"
    validation_index = SEASONS.index(validation_target)
    training_names = [season for season in SEASONS[:validation_index] if season in evidence]
    selected = [evidence[season] for season in training_names]
    candidate_priors = merge_season_evidence(
        selected,
        depth=min(winning_depth["depth"], len(selected)),
        half_life_seasons=winning_depth["half_life"],
    )
    archive = SeasonArchive(root / validation_target)
    candidate = _evaluate(
        archive,
        ExpectedPointsModelV3(
            priors=candidate_priors,
            transition_retention=winning_transition["retention"],
        ),
    )
    previous = SEASONS[validation_index - 1]
    v02_priors = build_prior_payload(root / previous, previous)
    baseline = _evaluate(archive, ExpectedPointsModel(priors=v02_priors))

    candidate_starter = candidate["cohorts"]["starters"]
    baseline_starter = baseline["cohorts"]["starters"]
    promotion_gate = {
        "ndcg_at_10_improves": candidate_starter["ndcg_at_10"] > baseline_starter["ndcg_at_10"],
        "top_10_overlap_not_worse": candidate_starter["top_10_overlap"] >= baseline_starter["top_10_overlap"],
        "mae_not_materially_worse": candidate_starter["mae"] <= baseline_starter["mae"] * 1.01,
    }
    promotion_gate["pass"] = all(promotion_gate.values())

    return {
        "protocol": {
            "source": "Vaastav Fantasy-Premier-League",
            "development_seasons": development_targets,
            "validation_season": validation_target,
            "warning": (
                "2025/26 is time-separated for this experiment but was previously inspected during "
                "v0.2 development, so current 2026/27 pre-deadline outcomes remain the cleanest final test."
            ),
            "field_semantics": "missing schema fields are unavailable, never observed zero",
            "selection": "maximize starter NDCG@10, then top-10 overlap, then lower MAE",
        },
        "available_seasons": sorted(evidence),
        "field_coverage": {season: evidence[season].coverage for season in sorted(evidence)},
        "depth_search": depth_results,
        "winning_depth": {"name": winning_depth_name, **winning_depth},
        "transition_search": transition_results,
        "winning_transition": {"key": winning_retention_key, **winning_transition},
        "validation_2025_26": {
            "xp_v0_2": baseline,
            "xp_v0_3_candidate": candidate,
            "promotion_gate": promotion_gate,
        },
        "recommended_current_priors": candidate_priors["history"],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, help="Directory containing season folders")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_experiment(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "winning_depth": result["winning_depth"]["name"],
        "winning_transition": result["winning_transition"]["retention"],
        "promotion_gate": result["validation_2025_26"]["promotion_gate"],
        "output": str(args.output),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
