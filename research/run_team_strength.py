from __future__ import annotations

import argparse
import json
from pathlib import Path

from fplengine.historical import _read_csv
from fplengine.team_model import Match, fit_team_ratings, predict_match, walk_forward_backtest

# Seasons before 2019/20 lack teams.csv/fixtures.csv in the public archive.
TRAIN_SEASONS = tuple(f"{year}-{str(year + 1)[-2:]}" for year in range(2019, 2025))
HOLDOUT_SEASON = "2025-26"


def load_season_matches(season_dir: Path, season: str) -> list[Match]:
    teams = {
        str(row["id"]): row["name"] for row in _read_csv(season_dir / "teams.csv")
    }
    matches: list[Match] = []
    for row in _read_csv(season_dir / "fixtures.csv"):
        try:
            event = int(row.get("event") or 0)
            home_goals = int(float(row.get("team_h_score")))
            away_goals = int(float(row.get("team_a_score")))
        except (TypeError, ValueError):
            continue
        if not 1 <= event <= 38 or row.get("finished", "").lower() != "true":
            continue
        home = teams.get(str(row.get("team_h")))
        away = teams.get(str(row.get("team_a")))
        if not home or not away or home == away:
            continue
        matches.append(
            Match(
                home=home,
                away=away,
                home_goals=home_goals,
                away_goals=away_goals,
                kickoff=row.get("kickoff_time") or "",
            )
        )
    return matches


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/team_strength_backtest.json"))
    parser.add_argument("--refresh-every", type=int, default=60)
    args = parser.parse_args()

    train = []
    for season in TRAIN_SEASONS:
        train.extend(load_season_matches(args.data_root / season, season))
    holdout = load_season_matches(args.data_root / HOLDOUT_SEASON, HOLDOUT_SEASON)
    matches = sorted(train + holdout, key=lambda match: match.kickoff)
    cutoff_index = len(train)
    # Guard against kickoff collisions reordering the split boundary.
    while any(match.kickoff < matches[cutoff_index - 1].kickoff for match in matches[:cutoff_index]):
        break

    report = walk_forward_backtest(
        matches,
        minimum_train=cutoff_index,
        refresh_every=args.refresh_every,
        dixon_coles=True,
    )

    final_ratings = fit_team_ratings(
        [match for match in matches if match.kickoff < matches[cutoff_index].kickoff],
        dixon_coles=True,
    )
    strongest = sorted(final_ratings.attack.items(), key=lambda item: item[1], reverse=True)[:6]
    weakest_defence = sorted(final_ratings.defence.items(), key=lambda item: item[1])[:6]
    demo_home = strongest[0][0]
    demo_away = sorted(final_ratings.attack)[-1]
    payload = {
        "experiment": "team-strength-walk-forward-v0.1",
        "train_seasons": list(TRAIN_SEASONS),
        "holdout_season": HOLDOUT_SEASON,
        "train_matches": cutoff_index,
        "holdout_matches": len(holdout),
        "refresh_every": args.refresh_every,
        "provenance": {
            "source": "Vaastav Fantasy-Premier-League archive fixtures.csv",
            "repository": "https://github.com/vaastav/Fantasy-Premier-League",
            "archive_commit": "c2add969e11ec19002a091f8aa60164c9a255854",
            "note": "Underlying data owned by FPL/Understat per archive licence; research use only",
        },
        "summary": report["summary"],
        "dixon_coles_rho": report["rho"],
        "final_fit_top_attack": strongest,
        "final_fit_best_defence": weakest_defence,
        "home_advantage": final_ratings.home_advantage,
        "example_predictions": [
            predict_match(final_ratings, demo_home, demo_away).to_dict(),
            predict_match(final_ratings, demo_away, demo_home).to_dict(),
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    print(f"rho={payload['dixon_coles_rho']} home_adv={final_ratings.home_advantage:.4f}")
    print(f"report={args.output}")


main()


