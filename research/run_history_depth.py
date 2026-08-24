"""Run the schema-aware v0.3 history-depth experiment.

Example:
    python research/run_history_depth.py --data-root /tmp/Fantasy-Premier-League/data
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fplengine.history_benchmark import run_history_depth_experiment

DEFAULT_PRIORS = tuple(f"{year}-{str(year + 1)[-2:]}" for year in range(2016, 2025))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--target-season", default="2025-26")
    parser.add_argument("--output", type=Path, default=Path("reports/history_depth_2025_26.json"))
    parser.add_argument("--from-event", type=int, default=6)
    parser.add_argument("--to-event", type=int, default=38)
    args = parser.parse_args()

    result = run_history_depth_experiment(
        args.data_root,
        target_season=args.target_season,
        prior_seasons=DEFAULT_PRIORS,
        first_event=args.from_event,
        last_event=args.to_event,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"target={result['target_season']} events={result['first_event']}-{result['last_event']}")
    print("top historical candidates")
    for row in result["leaderboard"][:10]:
        print(
            f"{row['label']}: starter NDCG@10={row['starter_ndcg_at_10']:.4f} "
            f"MAE={row['starter_mae']:.4f} top10={row['starter_top10_actual_mean']:.3f} "
            f"all MAE={row['all_mae']:.4f}"
        )
    print("simple baselines")
    for name, metrics in result["simple_baselines"].items():
        starter = metrics["starters"]
        print(
            f"{name}: starter NDCG@10={starter.get('ndcg_at_10', 0.0):.4f} "
            f"MAE={starter.get('mae', 0.0):.4f} top10={starter.get('top10_actual_mean', 0.0):.3f}"
        )
    print(f"report={args.output}")


if __name__ == "__main__":
    main()
