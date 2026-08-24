from __future__ import annotations

import argparse
import json
from pathlib import Path

from fplengine.interval_calibration_benchmark import run_interval_calibration_experiment

DEFAULT_PRIORS = tuple(f"{year}-{str(year + 1)[-2:]}" for year in range(2016, 2025))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--target-season", default="2025-26")
    parser.add_argument("--output", type=Path, default=Path("reports/interval_calibration_2025_26.json"))
    args = parser.parse_args()
    target_start = int(args.target_season.split("-", 1)[0])
    prior_seasons = tuple(
        season
        for season in DEFAULT_PRIORS
        if int(season.split("-", 1)[0]) < target_start
    )
    result = run_interval_calibration_experiment(
        args.data_root,
        target_season=args.target_season,
        prior_seasons=prior_seasons,
        global_factors=(1.0, 1.25, 1.5, 2.0),
        scopes=("none", "club_change"),
        transition_extras=(1.5,),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for row in result["leaderboard"]:
        print(
            f"{row['label']}: starterCov={row['starter_coverage']:.3f} "
            f"width={row['starter_mean_interval_width']:.2f} "
            f"above={row['starter_frac_above_upper']:.3f} below={row['starter_frac_below_lower']:.3f} "
            f"ndcg={row['starter_ndcg_at_10']:.4f}"
        )
    print(f"report={args.output}")


if __name__ == "__main__":
    main()
