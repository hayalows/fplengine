"""Normalize disposable compatibility details for very old Vaastav season layouts.

This module only mutates the ignored research checkout. It never changes the source
repository, invents football observations, or treats derived labels as real team names.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any


def _normalize_csv_encodings(season_dir: Path) -> int:
    """Convert legacy cp1252/latin-1 CSV bytes to UTF-8 without changing cell values."""
    changed = 0
    for path in sorted(season_dir.rglob("*.csv")):
        raw = path.read_bytes()
        try:
            raw.decode("utf-8-sig")
            continue
        except UnicodeDecodeError:
            pass
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        changed += 1
    return changed


def _derive_legacy_teams(season_dir: Path) -> bool:
    teams_path = season_dir / "teams.csv"
    players_path = season_dir / "players_raw.csv"
    if teams_path.exists() or not players_path.exists():
        return False
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
        return False
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
    return True


def normalize(root: Path) -> dict[str, Any]:
    team_metadata: list[str] = []
    encoding_files = 0
    for season_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        encoding_files += _normalize_csv_encodings(season_dir)
        if _derive_legacy_teams(season_dir):
            team_metadata.append(season_dir.name)
    return {
        "derived_team_metadata_seasons": team_metadata,
        "encoding_normalized_files": encoding_files,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    result = normalize(args.root)
    seasons = ", ".join(result["derived_team_metadata_seasons"]) or "none"
    print(f"derived teams.csv compatibility metadata for: {seasons}")
    print(f"normalized legacy CSV encodings to UTF-8: {result['encoding_normalized_files']} files")


if __name__ == "__main__":
    main()
