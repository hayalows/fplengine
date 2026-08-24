from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from fplengine.historical import _read_csv
from fplengine.team_model import (
    Match,
    canonical_team_name,
    fit_team_ratings,
    predict_match,
    walk_forward_backtest,
)

# Seasons before 2019/20 lack teams.csv/fixtures.csv in the public archive.
TRAIN_SEASONS = tuple(f"{year}-{str(year + 1)[-2:]}" for year in range(2019, 2025))
HOLDOUT_SEASON = "2025-26"


def load_season_matches(season_dir: Path, season: str) -> tuple[list[Match], dict[str, object]]:
    """Load completed matches with a full acceptance audit; no silent drops.

    Matches finished by FPL are accepted regardless of their stored event number:
    the 2019/20 archive labels COVID-postponed fixtures with event values beyond 38
    while they remain genuine league results. Duplicates on (home, away, kickoff)
    are rejected explicitly.
    """
    teams = {str(row["id"]): row["name"] for row in _read_csv(season_dir / "teams.csv")}
    rows = _read_csv(season_dir / "fixtures.csv")
    reasons: Counter[str] = Counter()
    matches: list[Match] = []
    seen: set[tuple[str, str, str]] = set()
    accepted_events: Counter[int] = Counter()
    for row in rows:
        home_raw = teams.get(str(row.get("team_h")))
        away_raw = teams.get(str(row.get("team_a")))
        if not home_raw or not away_raw:
            reasons["team_mapping_failure"] += 1
            continue
        if home_raw == away_raw:
            reasons["team_id_issue"] += 1
            continue
        try:
            event = int(float(row.get("event")))
        except (TypeError, ValueError):
            reasons["malformed_event"] += 1
            continue
        try:
            home_goals = int(float(row.get("team_h_score")))
            away_goals = int(float(row.get("team_a_score")))
        except (TypeError, ValueError):
            reasons["score_missing_or_unfinished"] += 1
            continue
        if row.get("finished", "").lower() != "true":
            reasons["not_finished"] += 1
            continue
        if not row.get("kickoff_time"):
            reasons["invalid_kickoff"] += 1
            continue
        home, away = canonical_team_name(home_raw), canonical_team_name(away_raw)
        key = (home, away, row["kickoff_time"])
        if key in seen:
            reasons["duplicate"] += 1
            continue
        seen.add(key)
        matches.append(
            Match(
                home=home,
                away=away,
                home_goals=home_goals,
                away_goals=away_goals,
                kickoff=row["kickoff_time"],
                event=event,
            )
        )
        accepted_events[event] += 1
    audit = {
        "rows_present": len(rows),
        "accepted": len(matches),
        "rejected": len(rows) - len(matches),
        "reasons": dict(sorted(reasons.items())),
        "accepted_outside_events_1_38": sum(
            count for event, count in accepted_events.items() if not 1 <= event <= 38
        ),
    }
    return matches, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("reports/team_strength_backtest.json"))
    parser.add_argument("--refresh-every", type=int, default=60)
    args = parser.parse_args()

    train: list[Match] = []
    season_audits = {}
    for season in TRAIN_SEASONS:
        season_matches, audit = load_season_matches(args.data_root / season, season)
        train.extend(season_matches)
        season_audits[season] = audit
    holdout, holdout_audit = load_season_matches(args.data_root / HOLDOUT_SEASON, HOLDOUT_SEASON)
    matches = sorted(train + holdout, key=lambda match: match.kickoff)
    cutoff_index = len(train)

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
        "experiment": "team-strength-walk-forward-v0.1-corrected",
        "train_seasons": list(TRAIN_SEASONS),
        "holdout_season": HOLDOUT_SEASON,
        "train_matches": cutoff_index,
        "holdout_matches": len(holdout),
        "refresh_every": args.refresh_every,
        "season_audit": {"train": season_audits, "holdout": holdout_audit},
        "provenance": {
            "source": "Vaastav Fantasy-Premier-League archive fixtures.csv",
            "repository": "https://github.com/vaastav/Fantasy-Premier-League",
            "archive_commit": "c2add969e11ec19002a091f8aa60164c9a255854",
            "note": "Underlying data owned by FPL/Understat per archive licence; research use only",
            "identity": "canonical slugs via fplengine.team_model.CANONICAL_TEAM_ALIASES",
        },
        "summary": report["summary"],
        "summary_prior_backed": report.get("summary_prior_backed"),
        "summary_fitted_teams_only": report.get("summary_fitted_teams_only"),
        "summary_early_events_le6": report.get("summary_early_events_le6"),
        "summary_late_events_gt6": report.get("summary_late_events_gt6"),
        "prior_backed_predictions": report.get("prior_backed_predictions"),
        "prior_backed_teams": report.get("prior_backed_teams"),
        "skipped": report.get("skipped"),
        "home_win_calibration_deciles": report.get("home_win_calibration_deciles"),
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
    print("prior-backed:", payload["prior_backed_predictions"], payload["prior_backed_teams"])
    print("skipped:", payload["skipped"])
    print(f"rho={payload['dixon_coles_rho']} home_adv={final_ratings.home_advantage:.4f}")
    print(f"report={args.output}")


if __name__ == "__main__":
    main()
