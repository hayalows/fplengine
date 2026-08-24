"""Field-aware multi-season historical priors for FPL Engine v0.3 research.

Historical FPL schemas change by season. Missing fields are never interpreted as
observed zeroes. Each rate carries its own evidence denominator and source coverage.
"""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

POSITION_NAMES = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
RATE_FIELDS = {
    "expected_goals": "xg90",
    "expected_assists": "xa90",
    "saves": "saves90",
    "defensive_contribution": "dc90",
    "bonus": "bonus90",
    "yellow_cards": "yellow90",
    "red_cards": "red90",
}


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    return int(_float(value))


def _read_csv(path: Path) -> tuple[list[dict[str, str]], set[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return rows, set(reader.fieldnames or [])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class SeasonEvidence:
    season: str
    players: dict[str, dict[str, Any]]
    positions: dict[str, dict[str, Any]]
    teams: dict[str, dict[str, Any]]
    league: dict[str, float]
    coverage: dict[str, bool]
    source_hashes: dict[str, str]


def build_season_evidence(season_dir: Path, season: str | None = None) -> SeasonEvidence:
    """Read one historical season while preserving field-availability semantics."""
    season_name = season or season_dir.name
    raw_players, _ = _read_csv(season_dir / "players_raw.csv")
    raw_teams, _ = _read_csv(season_dir / "teams.csv")
    teams_by_id = {_int(row.get("id")): row.get("name") or "" for row in raw_teams}
    meta: dict[int, dict[str, Any]] = {}
    for row in raw_players:
        element_id = _int(row.get("id"))
        code = _int(row.get("code"))
        position_id = _int(row.get("element_type"))
        if not element_id or not code or position_id not in POSITION_NAMES:
            continue
        meta[element_id] = {
            "code": code,
            "position": POSITION_NAMES[position_id],
            "team": teams_by_id.get(_int(row.get("team")), ""),
        }

    gw_paths = sorted(
        (season_dir / "gws").glob("gw*.csv"),
        key=lambda path: int(path.stem.removeprefix("gw")),
    )
    if not gw_paths:
        raise ValueError(f"No gameweek files found in {season_dir}")

    coverage = {
        "minutes": False,
        "starts": False,
        "expected_goals": False,
        "expected_assists": False,
        "saves": False,
        "defensive_contribution": False,
        "bonus": False,
        "yellow_cards": False,
        "red_cards": False,
        "total_points": False,
    }
    state: dict[str, dict[str, Any]] = {}
    rounds_seen: dict[str, set[int]] = defaultdict(set)
    field_minutes: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    role_games: dict[str, float] = defaultdict(float)
    fixture_team: dict[tuple[int, str], dict[str, Any]] = {}

    for path in gw_paths:
        rows, fields = _read_csv(path)
        for key in coverage:
            coverage[key] = coverage[key] or key in fields
        for row in rows:
            element_id = _int(row.get("element"))
            info = meta.get(element_id)
            if info is None:
                continue
            code = str(info["code"])
            position = row.get("position") or info["position"]
            team_name = row.get("team") or info["team"]
            player = state.setdefault(
                code,
                {
                    "position": position,
                    "team": team_name,
                    "minutes": 0.0,
                    "starts": 0.0,
                    "expected_goals": 0.0,
                    "expected_assists": 0.0,
                    "saves": 0.0,
                    "defensive_contribution": 0.0,
                    "bonus": 0.0,
                    "yellow_cards": 0.0,
                    "red_cards": 0.0,
                    "total_points": 0.0,
                    "starter_minutes": 0.0,
                    "substitute_appearances": 0.0,
                    "substitute_minutes": 0.0,
                    "evidence_minutes": {},
                    "coverage": {},
                },
            )
            player["team"] = team_name or player["team"]
            player["position"] = position or player["position"]
            minutes = _float(row.get("minutes")) if "minutes" in fields else 0.0
            if "minutes" in fields:
                player["minutes"] += minutes
            for field in RATE_FIELDS:
                if field in fields:
                    player[field] += _float(row.get(field))
                    field_minutes[code][field] += minutes
                    player["coverage"][field] = True
            if "total_points" in fields:
                player["total_points"] += _float(row.get("total_points"))
                player["coverage"]["total_points"] = True
            if "starts" in fields:
                starts = _float(row.get("starts"))
                player["starts"] += starts
                role_games[code] += 1.0
                player["coverage"]["starts"] = True
                if starts > 0:
                    player["starter_minutes"] += minutes
                elif minutes > 0:
                    player["substitute_appearances"] += 1.0
                    player["substitute_minutes"] += minutes
            rounds_seen[code].add(_int(row.get("round")) or int(path.stem.removeprefix("gw")))

            # Team xG evidence is available only when expected_goals exists in that era.
            if "expected_goals" in fields and "fixture" in fields:
                fixture_id = _int(row.get("fixture"))
                if fixture_id:
                    was_home = str(row.get("was_home")).lower() == "true"
                    fixture = fixture_team.setdefault(
                        (fixture_id, team_name),
                        {
                            "team": team_name,
                            "was_home": was_home,
                            "xg": 0.0,
                            "goals": None,
                        },
                    )
                    fixture["xg"] += _float(row.get("expected_goals"))
                    score_field = "team_h_score" if was_home else "team_a_score"
                    if score_field in fields:
                        fixture["goals"] = _int(row.get(score_field))

    for code, player in state.items():
        player["games"] = float(len(rounds_seen[code]))
        player["role_games"] = role_games[code]
        player["evidence_minutes"] = {
            field: round(value, 6) for field, value in field_minutes[code].items()
        }
        for key, value in list(player.items()):
            if isinstance(value, float):
                player[key] = round(value, 6)

    position_state: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "minutes": 0.0,
            "games": 0.0,
            "role_games": 0.0,
            "starts": 0.0,
            "starter_minutes": 0.0,
            "substitute_appearances": 0.0,
            "substitute_minutes": 0.0,
            "field_totals": defaultdict(float),
            "field_minutes": defaultdict(float),
        }
    )
    for player in state.values():
        pos = position_state[player["position"]]
        pos["minutes"] += _float(player["minutes"])
        pos["games"] += _float(player["games"])
        pos["role_games"] += _float(player["role_games"])
        pos["starts"] += _float(player["starts"])
        pos["starter_minutes"] += _float(player["starter_minutes"])
        pos["substitute_appearances"] += _float(player["substitute_appearances"])
        pos["substitute_minutes"] += _float(player["substitute_minutes"])
        for field in RATE_FIELDS:
            if player["coverage"].get(field):
                pos["field_totals"][field] += _float(player[field])
                pos["field_minutes"][field] += _float(player["evidence_minutes"].get(field))

    positions: dict[str, dict[str, Any]] = {}
    for position, pos in position_state.items():
        role_games_count = max(1.0, _float(pos["role_games"]))
        starts = max(1.0, _float(pos["starts"]))
        nonstarts = max(1.0, role_games_count - _float(pos["starts"]))
        sub_apps = max(1.0, _float(pos["substitute_appearances"]))
        output: dict[str, Any] = {
            "start_rate": _float(pos["starts"]) / role_games_count,
            "starter_minutes": _float(pos["starter_minutes"]) / starts,
            "cameo_rate": _float(pos["substitute_appearances"]) / nonstarts,
            "cameo_minutes": _float(pos["substitute_minutes"]) / sub_apps,
            "role_games": _float(pos["role_games"]),
            "evidence_minutes": {},
        }
        for field, rate_name in RATE_FIELDS.items():
            evidence = _float(pos["field_minutes"].get(field))
            output["evidence_minutes"][field] = evidence
            if evidence > 0:
                output[rate_name] = 90.0 * _float(pos["field_totals"].get(field)) / evidence
        positions[position] = output

    team_state: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "home_matches": 0.0,
            "away_matches": 0.0,
            "home_xg_for": 0.0,
            "home_xg_against": 0.0,
            "away_xg_for": 0.0,
            "away_xg_against": 0.0,
        }
    )
    fixture_pairs: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for (fixture_id, _), row in fixture_team.items():
        fixture_pairs[fixture_id].append(row)
    home_xg = away_xg = 0.0
    valid_fixtures = 0
    for rows in fixture_pairs.values():
        if len(rows) != 2:
            continue
        home = next((row for row in rows if row["was_home"]), None)
        away = next((row for row in rows if not row["was_home"]), None)
        if home is None or away is None:
            continue
        valid_fixtures += 1
        home_xg += _float(home["xg"])
        away_xg += _float(away["xg"])
        for row, opponent in ((home, away), (away, home)):
            team = team_state[row["team"]]
            venue = "home" if row["was_home"] else "away"
            team[f"{venue}_matches"] += 1.0
            team[f"{venue}_xg_for"] += _float(row["xg"])
            team[f"{venue}_xg_against"] += _float(opponent["xg"])

    source_files = [season_dir / "players_raw.csv", season_dir / "teams.csv", *gw_paths]
    return SeasonEvidence(
        season=season_name,
        players=state,
        positions=positions,
        teams={name: dict(values) for name, values in team_state.items()},
        league={
            "fixtures": float(valid_fixtures),
            "home_xg": home_xg / max(1, valid_fixtures),
            "away_xg": away_xg / max(1, valid_fixtures),
        },
        coverage=coverage,
        source_hashes={
            path.relative_to(season_dir).as_posix(): _sha256(path) for path in source_files
        },
    )


def merge_season_evidence(
    seasons: list[SeasonEvidence],
    *,
    depth: int | None = None,
    half_life_seasons: float | None = None,
) -> dict[str, Any]:
    """Merge seasons into a v0.3 prior with field-specific evidence denominators."""
    selected = seasons[-depth:] if depth else list(seasons)
    if not selected:
        return {
            "schema_version": 2,
            "season": None,
            "league": {},
            "positions": {},
            "teams": {},
            "players": {},
            "history": {"seasons": []},
        }

    weights: list[float] = []
    for index in range(len(selected)):
        age = len(selected) - 1 - index
        weight = 1.0 if half_life_seasons is None else 0.5 ** (age / half_life_seasons)
        weights.append(weight)

    player_acc: dict[str, dict[str, Any]] = {}
    position_acc: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "role_games": 0.0,
            "starts": 0.0,
            "starter_minutes": 0.0,
            "substitute_appearances": 0.0,
            "substitute_minutes": 0.0,
            "field_totals": defaultdict(float),
            "field_minutes": defaultdict(float),
        }
    )
    latest_team_by_code: dict[str, str] = {}
    team_history_by_code: dict[str, list[dict[str, str]]] = defaultdict(list)

    for season, weight in zip(selected, weights):
        for code, row in season.players.items():
            acc = player_acc.setdefault(
                code,
                {
                    "position": row["position"],
                    "team": row["team"],
                    "minutes": 0.0,
                    "starts": 0.0,
                    "games": 0.0,
                    "role_games": 0.0,
                    "starter_minutes": 0.0,
                    "substitute_appearances": 0.0,
                    "substitute_minutes": 0.0,
                    "expected_goals": 0.0,
                    "expected_assists": 0.0,
                    "saves": 0.0,
                    "defensive_contribution": 0.0,
                    "bonus": 0.0,
                    "yellow_cards": 0.0,
                    "red_cards": 0.0,
                    "total_points": 0.0,
                    "evidence_minutes": defaultdict(float),
                    "coverage_seasons": defaultdict(int),
                },
            )
            acc["position"] = row["position"]
            acc["team"] = row["team"]
            latest_team_by_code[code] = row["team"]
            team_history_by_code[code].append({"season": season.season, "team": row["team"]})
            for field in (
                "minutes",
                "games",
                "total_points",
            ):
                acc[field] += weight * _float(row.get(field))
            if row.get("coverage", {}).get("starts"):
                acc["starts"] += weight * _float(row.get("starts"))
                acc["role_games"] += weight * _float(row.get("role_games"))
                acc["starter_minutes"] += weight * _float(row.get("starter_minutes"))
                acc["substitute_appearances"] += weight * _float(row.get("substitute_appearances"))
                acc["substitute_minutes"] += weight * _float(row.get("substitute_minutes"))
                acc["coverage_seasons"]["starts"] += 1
            for field in RATE_FIELDS:
                if row.get("coverage", {}).get(field):
                    acc[field] += weight * _float(row.get(field))
                    acc["evidence_minutes"][field] += weight * _float(
                        row.get("evidence_minutes", {}).get(field)
                    )
                    acc["coverage_seasons"][field] += 1

    players: dict[str, dict[str, Any]] = {}
    for code, acc in player_acc.items():
        acc["team"] = latest_team_by_code.get(code, acc["team"])
        acc["team_history"] = team_history_by_code[code]
        acc["evidence_minutes"] = dict(acc["evidence_minutes"])
        acc["coverage_seasons"] = dict(acc["coverage_seasons"])
        players[code] = acc
        pos = position_acc[acc["position"]]
        pos["role_games"] += _float(acc["role_games"])
        pos["starts"] += _float(acc["starts"])
        pos["starter_minutes"] += _float(acc["starter_minutes"])
        pos["substitute_appearances"] += _float(acc["substitute_appearances"])
        pos["substitute_minutes"] += _float(acc["substitute_minutes"])
        for field in RATE_FIELDS:
            pos["field_totals"][field] += _float(acc[field])
            pos["field_minutes"][field] += _float(acc["evidence_minutes"].get(field))

    positions: dict[str, dict[str, Any]] = {}
    for position, acc in position_acc.items():
        role_games = max(1.0, _float(acc["role_games"]))
        starts = max(1.0, _float(acc["starts"]))
        nonstarts = max(1.0, role_games - _float(acc["starts"]))
        sub_apps = max(1.0, _float(acc["substitute_appearances"]))
        result: dict[str, Any] = {
            "start_rate": _float(acc["starts"]) / role_games,
            "starter_minutes": _float(acc["starter_minutes"]) / starts,
            "cameo_rate": _float(acc["substitute_appearances"]) / nonstarts,
            "cameo_minutes": _float(acc["substitute_minutes"]) / sub_apps,
            "role_games": _float(acc["role_games"]),
            "evidence_minutes": {},
        }
        for field, rate_name in RATE_FIELDS.items():
            evidence = _float(acc["field_minutes"].get(field))
            result["evidence_minutes"][field] = evidence
            if evidence > 0:
                result[rate_name] = 90.0 * _float(acc["field_totals"].get(field)) / evidence
        positions[position] = result

    team_acc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    league_weight = league_home = league_away = 0.0
    for season, weight in zip(selected, weights):
        if season.league.get("fixtures", 0.0) <= 0:
            continue
        league_weight += weight
        league_home += weight * _float(season.league.get("home_xg"))
        league_away += weight * _float(season.league.get("away_xg"))
        for name, row in season.teams.items():
            for field, value in row.items():
                team_acc[name][field] += weight * _float(value)

    return {
        "schema_version": 2,
        "season": selected[-1].season,
        "league": {
            "home_xg": league_home / max(league_weight, 1e-9),
            "away_xg": league_away / max(league_weight, 1e-9),
        },
        "positions": positions,
        "teams": {name: dict(row) for name, row in team_acc.items()},
        "players": players,
        "history": {
            "seasons": [row.season for row in selected],
            "weights": {row.season: round(weight, 6) for row, weight in zip(selected, weights)},
            "depth": len(selected),
            "half_life_seasons": half_life_seasons,
            "field_coverage": {row.season: row.coverage for row in selected},
            "principle": "missing historical fields are unavailable evidence, never zero observations",
        },
    }
