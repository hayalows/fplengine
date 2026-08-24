"""Run role-transition prior-decay diagnostics on opening gameweeks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fplengine.role_transition_benchmark import run_role_transition_experiment

DEFAULT_PRIORS = tuple(f"{year}-{str(year + 1)[-2:]}" for year in range(2016, 2025))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--target-season", default="2025-26")
    parser.add_argument(
        "--output", type=Path, default=Path("reports/role_transition_2025_26.json")
    )
    parser.add_argument("--from-event", type=int, default=1)
    parser.add_argument("--to-event", type=int, default=10)
    args = parser.parse_args()

    result = run_role_transition_experiment(
        args.data_root,
        target_season=args.target_season,
        prior_seasons=DEFAULT_PRIORS,
        first_event=args.from_event,
        last_event=args.to_event,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"target={result['target_season']} events={result['events']}")
    print(f"cohorts={result['profile_counts']}")
    print("transition role-weight candidates")
    for row in result["leaderboard"]:
        print(
            f"weight={row['transition_weight']:.2f} "
            f"transition minutes MAE={row['transition_minutes_mae']:.3f} "
            f"points MAE={row['transition_points_mae']:.3f} "
            f"starter NDCG@10={row['all_starter_ndcg_at_10']:.4f} "
            f"coverage={row['transition_interval_coverage']:.3f} "
            f"risk={row['transition_mean_reported_risk']:.3f}"
        )
    print(f"report={args.output}")


if __name__ == "__main__":
    main()
