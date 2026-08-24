"""Run the component-specific v0.3 historical-memory experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fplengine.component_history_benchmark import run_component_history_experiment

DEFAULT_PRIORS = tuple(f"{year}-{str(year + 1)[-2:]}" for year in range(2016, 2025))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--target-season", default="2025-26")
    parser.add_argument(
        "--output", type=Path, default=Path("reports/component_history_2025_26.json")
    )
    parser.add_argument("--from-event", type=int, default=6)
    parser.add_argument("--to-event", type=int, default=38)
    args = parser.parse_args()

    result = run_component_history_experiment(
        args.data_root,
        target_season=args.target_season,
        prior_seasons=DEFAULT_PRIORS,
        first_event=args.from_event,
        last_event=args.to_event,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"target={result['target_season']} events={result['first_event']}-{result['last_event']}")
    print("top component-history candidates")
    for row in result["leaderboard"][:12]:
        print(
            f"{row['label']}: role={row['role_seasons']} attack={row['attack_seasons']} "
            f"ancillary={row['ancillary_seasons']} NDCG@10={row['starter_ndcg_at_10']:.4f} "
            f"MAE={row['starter_mae']:.4f} top10={row['starter_top10_actual_mean']:.3f}"
        )
    print("marginal component effects")
    for component, rows in result["marginals"].items():
        print(component)
        for window, metrics in rows.items():
            print(
                f"  {window} seasons: NDCG@10={metrics['mean_starter_ndcg_at_10']:.4f} "
                f"MAE={metrics['mean_starter_mae']:.4f} "
                f"top10={metrics['mean_top10_actual']:.3f}"
            )
    print(f"report={args.output}")


if __name__ == "__main__":
    main()
