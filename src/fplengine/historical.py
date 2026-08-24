"""Schema-aware historical evidence for leakage-safe multi-season FPL experiments.

This module is intentionally separate from the live v0.2 prior path. Historical FPL
archives change schema across eras, so an absent column must never be interpreted as an
observed zero. The output keeps per-field exposure and can be merged with recency decay.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

POSITION_NAMES = {"GK", "DEF", "MID", "FWD"}
RATE_FIELDS = (
    "expected_goals",
    "expected_assists",
    "saves",
    "defensive_contribution",
    "bonus",
    "yellow_cards",
    "red_cards",
)
POSITION_RATE_NAMES = {
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


def _csv_text(path: Path) -> str:
    """Decode historical archive CSVs without silently replacing characters.

    Recent Vaastav seasons are UTF-8, while some early seasons are Latin-1. Decode
    UTF-8 (including an optional BOM) first and fall back to Latin-1 only on a genuine
    Unicode decode failure. Latin-1 is lossless for every byte, so this preserves names
    and headers instead of hiding corruption with replacement characters.
    """
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(_csv_text(path), newline="")))


def _fieldnames(path: Path) -> set[str]:
    reader = csv.reader(io.StringIO(_csv_text(path), newline=""))
    return set(next(reader, []))


def season_field_manifest(season_dir: Path) -> dict[str, bool]:
    """Return fields genuinely present in a season archive.

    The union is used because historical collectors occasionally add a field after GW1.
    Presence means the archive exposes the field, not that every player has a non-zero
    value.
    """
    names: set[str] = set()
    for path in sorted((season_dir / "gws").glob("gw*.csv")):
        names.update(_fieldnames(path))
    tracked = {
        "minutes",
        "starts",
        "total_points",
        *RATE_FIELDS,
    }
    return {field: field in names for field in sorted(tracked)}


def _season_sort_key(season: str | None) -> int:
    if not season:
        return -1
    try:
        return int(str(season).split("-", 1)[0])
    except ValueError:
        return -1


def build_season_evidence(season_dir: Path, season: str) -> dict[str, Any]:
    """Normalize one completed season while preserving field availability.

    Only observed fields receive exposure. For example, 2018/19 minutes do not dilute a
    2024/25 xG rate because the older archive did not contain expected_goals.
    """
    player_rows = _read_csv(season_dir / "players_raw.csv")
    id_to_code = {_int(row.get("id")): _int(row.get("code")) for row in player_rows}
    manifest = season_field_manifest(season_dir)
    gw_paths = sorted(
        (season_dir / "gws").glob("gw*.csv"),
        key=lambda path: int(path.stem.removeprefix("gw")),
    )
    if not gw_paths:
        raise ValueError(f"No gameweek files found in {season_dir}")

    players: dict[int, dict[str, Any]] = {}
    rounds: dict[int, set[int]] = defaultdict(set)
    for path in gw_paths:
        for row in _read_csv(path):
            element_id = _int(row.get("element"))
            code = id_to_code.get(element_id)
            position = row.get("position") or ""
            if not code or position not in POSITION_NAMES:
                continue
            state = players.setdefault(
                code,
                {
                    "position": position,
                    "team": row.get("team") or "",
                    "minutes": 0.0,
                    "total_points": 0.0,
                    "opportunities": 0.0,
                    "starts": 0.0,
                    "starts_opportunities": 0.0,
                    "starter_minutes": 0.0,
                    "substitute_appearances": 0.0,
                    "substitute_minutes": 0.0,
                    **{field: 0.0 for field in RATE_FIELDS},
                    **{f"{field}_minutes": 0.0 for field in RATE_FIELDS},
                },
            )
            state["team"] = row.get("team") or state["team"]
            minutes = _float(row.get("minutes"))
            state["minutes"] += minutes
            state["total_points"] += _float(row.get("total_points"))
            state["opportunities"] += 1.0
            rounds[code].add(_int(row.get("round")))

            if manifest.get("starts"):
                starts = _float(row.get("starts"))
                state["starts"] += starts
                state["starts_opportunities"] += 1.0
                if starts > 0:
                    state["starter_minutes"] += minutes
                elif minutes > 0:
                    state["substitute_appearances"] += 1.0
                    state["substitute_minutes"] += minutes

            for field in RATE_FIELDS:
                if not manifest.get(field):
                    continue
                value = row.get(field)
                if value is None or value == "":
                    continue
                state[field] += _float(value)
                state[f"{field}_minutes"] += minutes

    for code, state in players.items():
        state["games"] = float(len(rounds[code]))
        # Remove fake zero-valued evidence for fields that this season never measured.
        for field in RATE_FIELDS:
            if not manifest.get(field):
                state.pop(field, None)
                state.pop(f"{field}_minutes", None)
        if not manifest.get("starts"):
            for field in (
                "starts",
                "starts_opportunities",
                "starter_minutes",
                "substitute_appearances",
                "substitute_minutes",
            ):
                state.pop(field, None)
        for key, value in list(state.items()):
            if isinstance(value, float):
                state[key] = round(value, 6)

    return {
        "schema_version": 2,
        "season": season,
        "field_availability": manifest,
        "source": {
            "name": "Vaastav Fantasy-Premier-League historical archive",
            "repository": "https://github.com/vaastav/Fantasy-Premier-League",
            "raw_files_retained": False,
        },
        "players": {str(code): state for code, state in sorted(players.items())},
    }


def _weighted_add(target: dict[str, float], source: dict[str, Any], key: str, weight: float) -> None:
    if key in source:
        target[key] = target.get(key, 0.0) + weight * _float(source[key])


def _position_priors(players: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for state in players.values():
        position = str(state.get("position") or "")
        if position not in POSITION_NAMES:
            continue
        aggregate = totals[position]
        for field in RATE_FIELDS:
            _weighted_add(aggregate, state, field, 1.0)
            _weighted_add(aggregate, state, f"{field}_minutes", 1.0)
        for field in (
            "starts",
            "starts_opportunities",
            "starter_minutes",
            "substitute_appearances",
            "substitute_minutes",
        ):
            _weighted_add(aggregate, state, field, 1.0)

    result: dict[str, dict[str, float]] = {}
    for position, state in totals.items():
        row: dict[str, float] = {}
        for field, output_name in POSITION_RATE_NAMES.items():
            exposure = state.get(f"{field}_minutes", 0.0)
            if exposure > 0:
                row[output_name] = round(90.0 * state.get(field, 0.0) / exposure, 6)
        opportunities = state.get("starts_opportunities", 0.0)
        starts = state.get("starts", 0.0)
        if opportunities > 0:
            row["start_rate"] = round(starts / opportunities, 6)
        if starts > 0:
            row["starter_minutes"] = round(state.get("starter_minutes", 0.0) / starts, 6)
        nonstarts = max(0.0, opportunities - starts)
        sub_apps = state.get("substitute_appearances", 0.0)
        if nonstarts > 0:
            row["cameo_rate"] = round(sub_apps / nonstarts, 6)
        if sub_apps > 0:
            row["cameo_minutes"] = round(
                state.get("substitute_minutes", 0.0) / sub_apps, 6
            )
        result[position] = row
    return result


def merge_season_evidence(
    payloads: Iterable[dict[str, Any]],
    *,
    max_seasons: int | None = None,
    decay: float = 1.0,
) -> dict[str, Any]:
    """Merge historical seasons into one prior with explicit recency weighting.

    The newest season receives weight 1.0, the previous season ``decay``, then
    ``decay**2`` and so on. Field-specific exposure is merged with the same weight, so
    unavailable historical columns cannot act like zero observations.
    """
    if not 0.0 < decay <= 1.0:
        raise ValueError("decay must be in (0, 1]")
    ordered = sorted(payloads, key=lambda row: _season_sort_key(row.get("season")), reverse=True)
    if max_seasons is not None:
        if max_seasons <= 0:
            raise ValueError("max_seasons must be positive")
        ordered = ordered[:max_seasons]
    if not ordered:
        return {
            "schema_version": 2,
            "season": None,
            "source_seasons": [],
            "positions": {},
            "teams": {},
            "league": {},
            "players": {},
        }

    merged: dict[str, dict[str, Any]] = {}
    availability: dict[str, list[str]] = defaultdict(list)
    for age, payload in enumerate(ordered):
        weight = decay**age
        season = str(payload.get("season"))
        for field, present in payload.get("field_availability", {}).items():
            if present:
                availability[field].append(season)
        for code, source in payload.get("players", {}).items():
            target = merged.setdefault(
                str(code),
                {
                    "position": source.get("position") or "",
                    "team": source.get("team") or "",
                    "games": 0.0,
                    "minutes": 0.0,
                    "total_points": 0.0,
                    "opportunities": 0.0,
                },
            )
            # The latest observed team/position wins; older seasons only add evidence.
            if age == 0 or not target.get("team"):
                target["team"] = source.get("team") or target.get("team")
                target["position"] = source.get("position") or target.get("position")
            for field in (
                "games",
                "minutes",
                "total_points",
                "opportunities",
                "starts",
                "starts_opportunities",
                "starter_minutes",
                "substitute_appearances",
                "substitute_minutes",
                *RATE_FIELDS,
                *(f"{field}_minutes" for field in RATE_FIELDS),
            ):
                _weighted_add(target, source, field, weight)

    for state in merged.values():
        for key, value in list(state.items()):
            if isinstance(value, float):
                state[key] = round(value, 6)

    seasons = [str(row.get("season")) for row in ordered]
    return {
        "schema_version": 2,
        "season": seasons[0],
        "source_seasons": seasons,
        "decay": decay,
        "field_seasons": {key: values for key, values in sorted(availability.items())},
        "league": {},
        "teams": {},
        "positions": _position_priors(merged),
        "players": dict(sorted(merged.items())),
    }


def history_window_variants(
    payloads: Iterable[dict[str, Any]],
    *,
    windows: tuple[int, ...] = (1, 2, 3, 5, 7, 10),
    decays: tuple[float, ...] = (1.0, 0.85, 0.70),
) -> dict[str, dict[str, Any]]:
    """Create reproducible prior candidates for the history-depth experiment."""
    materialized = list(payloads)
    result: dict[str, dict[str, Any]] = {}
    for window in windows:
        for decay in decays:
            label = f"history_{window}y_decay_{decay:.2f}"
            result[label] = merge_season_evidence(
                materialized, max_seasons=window, decay=decay
            )
    return result
