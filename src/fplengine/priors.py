"""Build and load compact, source-attributed prior-season football evidence."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from importlib.resources import files
from pathlib import Path
from typing import Any

POSITION_IDS = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    return int(_float(value))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def build_prior_payload(season_dir: Path, season: str) -> dict[str, Any]:
    """Aggregate one completed season without retaining the raw archive."""
    player_rows = _read_csv(season_dir / "players_raw.csv")
    team_rows = _read_csv(season_dir / "teams.csv")
    id_to_code = {_int(row["id"]): _int(row["code"]) for row in player_rows}
    team_id_to_name = {_int(row["id"]): row["name"] for row in team_rows}

    player_state: dict[int, dict[str, Any]] = {}
    player_rounds: dict[int, set[int]] = defaultdict(set)
    fixture_team: dict[tuple[int, str], dict[str, Any]] = {}

    stat_fields = (
        "minutes",
        "starts",
        "expected_goals",
        "expected_assists",
        "saves",
        "defensive_contribution",
        "bonus",
        "yellow_cards",
        "red_cards",
        "total_points",
    )
    gw_paths = sorted(
        (season_dir / "gws").glob("gw*.csv"),
        key=lambda path: int(path.stem.removeprefix("gw")),
    )
    if len(gw_paths) != 38:
        raise ValueError(f"Expected 38 gameweek files in {season_dir}, found {len(gw_paths)}")

    for path in gw_paths:
        for row in _read_csv(path):
            element_id = _int(row.get("element"))
            code = id_to_code.get(element_id)
            if not code:
                continue
            position = row.get("position") or ""
            if position not in POSITION_IDS:
                continue
            state = player_state.setdefault(
                code,
                {
                    "position": position,
                    "team": row.get("team") or "",
                    **{field: 0.0 for field in stat_fields},
                    "starter_minutes": 0.0,
                    "substitute_appearances": 0,
                    "substitute_minutes": 0.0,
                },
            )
            state["team"] = row.get("team") or state["team"]
            for field in stat_fields:
                state[field] += _float(row.get(field))
            minutes = _float(row.get("minutes"))
            starts = _int(row.get("starts"))
            if starts:
                state["starter_minutes"] += minutes
            elif minutes > 0:
                state["substitute_appearances"] += 1
                state["substitute_minutes"] += minutes
            player_rounds[code].add(_int(row.get("round")))

            fixture_id = _int(row.get("fixture"))
            team_name = row.get("team") or ""
            fixture = fixture_team.setdefault(
                (fixture_id, team_name),
                {
                    "team": team_name,
                    "opponent": team_id_to_name.get(_int(row.get("opponent_team")), ""),
                    "was_home": str(row.get("was_home")).lower() == "true",
                    "xg": 0.0,
                    "goals": None,
                },
            )
            fixture["xg"] += _float(row.get("expected_goals"))
            fixture["goals"] = _int(
                row.get("team_h_score") if fixture["was_home"] else row.get("team_a_score")
            )

    for code, state in player_state.items():
        state["games"] = len(player_rounds[code])
        for key, value in list(state.items()):
            if isinstance(value, float):
                state[key] = round(value, 6)

    team_state: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "home_matches": 0.0,
            "away_matches": 0.0,
            "home_xg_for": 0.0,
            "home_xg_against": 0.0,
            "away_xg_for": 0.0,
            "away_xg_against": 0.0,
            "goals_for": 0.0,
            "goals_against": 0.0,
        }
    )
    fixture_pairs: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for (fixture_id, _), row in fixture_team.items():
        fixture_pairs[fixture_id].append(row)
    home_xg_total = away_xg_total = 0.0
    valid_fixtures = 0
    for rows in fixture_pairs.values():
        if len(rows) != 2:
            continue
        home = next((row for row in rows if row["was_home"]), None)
        away = next((row for row in rows if not row["was_home"]), None)
        if home is None or away is None:
            continue
        valid_fixtures += 1
        home_xg_total += home["xg"]
        away_xg_total += away["xg"]
        for row, opponent in ((home, away), (away, home)):
            state = team_state[row["team"]]
            venue = "home" if row["was_home"] else "away"
            state[f"{venue}_matches"] += 1
            state[f"{venue}_xg_for"] += row["xg"]
            state[f"{venue}_xg_against"] += opponent["xg"]
            state["goals_for"] += row["goals"] or 0
            state["goals_against"] += opponent["goals"] or 0

    position_state: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for state in player_state.values():
        aggregate = position_state[state["position"]]
        for field in stat_fields:
            aggregate[field] += _float(state[field])
        aggregate["games"] += _float(state["games"])
        aggregate["starter_minutes"] += _float(state["starter_minutes"])
        aggregate["substitute_appearances"] += _float(state["substitute_appearances"])
        aggregate["substitute_minutes"] += _float(state["substitute_minutes"])

    position_priors: dict[str, dict[str, float]] = {}
    for position, state in position_state.items():
        minutes = max(1.0, state["minutes"])
        starts = max(1.0, state["starts"])
        nonstarts = max(1.0, state["games"] - state["starts"])
        sub_apps = max(1.0, state["substitute_appearances"])
        position_priors[position] = {
            "xg90": round(90 * state["expected_goals"] / minutes, 6),
            "xa90": round(90 * state["expected_assists"] / minutes, 6),
            "saves90": round(90 * state["saves"] / minutes, 6),
            "dc90": round(90 * state["defensive_contribution"] / minutes, 6),
            "bonus90": round(90 * state["bonus"] / minutes, 6),
            "yellow90": round(90 * state["yellow_cards"] / minutes, 6),
            "red90": round(90 * state["red_cards"] / minutes, 6),
            "start_rate": round(state["starts"] / max(1.0, state["games"]), 6),
            "starter_minutes": round(state["starter_minutes"] / starts, 6),
            "cameo_rate": round(state["substitute_appearances"] / nonstarts, 6),
            "cameo_minutes": round(state["substitute_minutes"] / sub_apps, 6),
        }

    source_files = [season_dir / "players_raw.csv", season_dir / "teams.csv", *gw_paths]
    return {
        "schema_version": 1,
        "season": season,
        "source": {
            "name": "Vaastav Fantasy-Premier-League historical archive",
            "repository": "https://github.com/vaastav/Fantasy-Premier-League",
            "raw_files_retained": False,
            "file_sha256": {path.relative_to(season_dir).as_posix(): _sha256(path) for path in source_files},
        },
        "league": {
            "fixtures": valid_fixtures,
            "home_xg": round(home_xg_total / max(1, valid_fixtures), 6),
            "away_xg": round(away_xg_total / max(1, valid_fixtures), 6),
        },
        "positions": position_priors,
        "teams": {
            name: {key: round(value, 6) for key, value in state.items()}
            for name, state in sorted(team_state.items())
        },
        "players": {str(code): state for code, state in sorted(player_state.items())},
    }


def write_prior_payload(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_default_priors() -> dict[str, Any]:
    resource = files("fplengine").joinpath("data", "priors_2025_26.json")
    if not resource.is_file():
        return {"schema_version": 1, "season": None, "league": {}, "positions": {}, "teams": {}, "players": {}}
    return json.loads(resource.read_text("utf-8"))
