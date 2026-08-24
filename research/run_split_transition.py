from __future__ import annotations

import argparse
import json
from pathlib import Path

from fplengine.split_transition_benchmark import run_split_transition_experiment

DEFAULT_PRIORS = tuple(f"{year}-{str(year + 1)[-2:]}" for year in range(2016, 2025))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/split_transition_2025_26.json"))
    args = parser.parse_args()
    result = run_split_transition_experiment(
        args.data_root,
        target_season="2025-26",
        prior_seasons=DEFAULT_PRIORS,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("profile counts:", json.dumps(result["profile_counts"], sort_keys=True))
    for row in result["leaderboard"]:
        print(
            f"{row['label']}: NDCG={row['all_starter_ndcg_at_10']:.4f} "
            f"club minMAE={row['club_minutes_mae']:.3f} club ptMAE={row['club_points_mae']:.3f} "
            f"estab minMAE={row['transfer_established_minutes_mae']} "
            f"toProm minMAE={row['transfer_to_promoted_minutes_mae']} "
            f"promoted minMAE={row['promoted_minutes_mae']:.3f}"
        )
    print(f"report={args.output}")


if __name__ == "__main__":
    main()
