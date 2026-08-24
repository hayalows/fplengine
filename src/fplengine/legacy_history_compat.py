"""Create disposable compatibility metadata for very old Vaastav season layouts.

This only mutates the ignored research checkout. It never changes the source repository
or treats derived team labels as real observed team names.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def normalize(root: Path) -> list[str]:
    changed: list[str] = []
    for season_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        teams_path = season_dir / "teams.csv"
        players_path = season_dir / "players_raw.csv"
        if teams_path.exists() or not players_path.exists():
            continue
        with players_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        teams: dict[int, int] = {}
        for row in rows:
            try:
                team_id = int(float(row.get("team") or 0))
                team_code = int(float(row.get("team_code") or team_id))
            except (TypeError, ValueError):
                continue
            if team_id:
                teams[team_id] = team_code
        if not teams:
            continue
        with teams_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["id", "code", "name", "short_name"])
            writer.writeheader()
            for team_id, team_code in sorted(teams.items()):
                writer.writerow(
                    {
                        "id": team_id,
                        "code": team_code,
                        "name": f"legacy_team_{team_id}",
                        "short_name": f"L{team_id:02d}",
                    }
                )
        changed.append(season_dir.name)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    changed = normalize(args.root)
    print(f"created derived teams.csv compatibility metadata for: {', '.join(changed) or 'none'}")


if __name__ == "__main__":
    main()
