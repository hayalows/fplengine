"""Leakage-aware walk-forward benchmarking on public historical FPL archives."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

from .api_client import Snapshot
from .model import POSITION_NAMES, ExpectedPointsModel

POSITION_IDS = {value: key for key, value in POSITION_NAMES.items()}
CUMULATIVE_FIELDS = (
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


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    return int(_float(value))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@dataclass(frozen=True)
class Actual:
    points: float
    minutes: int
    starts: int
    position: str


class SeasonArchive:
    def __init__(self, season_dir: Path) -> None:
        self.season_dir = season_dir
        players = _read_csv(season_dir / "players_raw.csv")
        self.id_to_code = {_int(row["id"]): _int(row["code"]) for row in players}
        self.teams = _read_csv(season_dir / "teams.csv")
        self.team_name_to_id = {row["name"]: _int(row["id"]) for row in self.teams}
        self.fixtures = _read_csv(season_dir / "fixtures.csv")
        self.gameweeks = {
            event: _read_csv(season_dir / "gws" / f"gw{event}.csv")
            for event in range(1, 39)
        }
        self._cumulative: dict[int, dict[int, dict[str, float]]] = {}
        self._points_history: dict[int, dict[int, float]] = defaultdict(dict)
        for event, rows in self.gameweeks.items():
            per_player: dict[int, float] = defaultdict(float)
            for row in rows:
                element_id = _int(row.get("element"))
                code = self.id_to_code.get(element_id)
                if code:
                    per_player[code] += _float(row.get("total_points"))
            for code, points in per_player.items():
                self._points_history[code][event] = points

    def cumulative_before(self, event: int) -> dict[int, dict[str, float]]:
        if event in self._cumulative:
            return self._cumulative[event]
        state: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for previous in range(1, event):
            seen_round: set[int] = set()
            for row in self.gameweeks[previous]:
                element_id = _int(row.get("element"))
                if element_id not in self.id_to_code:
                    continue
                current = state[element_id]
                for field in CUMULATIVE_FIELDS:
                    current[field] += _float(row.get(field))
                seen_round.add(element_id)
            for element_id in seen_round:
                state[element_id]["roster_gameweeks"] += 1
        result = {element_id: dict(values) for element_id, values in state.items()}
        self._cumulative[event] = result
        return result

    def _target_rows(self, event: int) -> dict[int, list[dict[str, str]]]:
        grouped: dict[int, list[dict[str, str]]] = defaultdict(list)
        for row in self.gameweeks[event]:
            grouped[_int(row.get("element"))].append(row)
        return grouped

    def actuals(self, event: int) -> dict[int, Actual]:
        actuals: dict[int, Actual] = {}
        for element_id, rows in self._target_rows(event).items():
            actuals[element_id] = Actual(
                points=sum(_float(row.get("total_points")) for row in rows),
                minutes=sum(_int(row.get("minutes")) for row in rows),
                starts=sum(_int(row.get("starts")) for row in rows),
                position=rows[0].get("position") or "",
            )
        return actuals

    def archive_xp(self, event: int) -> dict[int, float]:
        return {
            element_id: sum(_float(row.get("xP")) for row in rows)
            for element_id, rows in self._target_rows(event).items()
        }

    def simple_baselines(self, event: int) -> dict[str, dict[int, float]]:
        rows = self._target_rows(event)
        baselines: dict[str, dict[int, float]] = {
            "zero": {},
            "previous_five_mean": {},
            "last_gameweek": {},
            "position_mean": {},
            "archive_fpl_xp_timing_unverified": self.archive_xp(event),
        }
        position_values: dict[str, list[float]] = defaultdict(list)
        for previous in range(1, event):
            for element_id, actual in self.actuals(previous).items():
                position_values[actual.position].append(actual.points)
        position_mean = {
            position: mean(values) if values else 0.0
            for position, values in position_values.items()
        }
        for element_id, target in rows.items():
            code = self.id_to_code.get(element_id)
            history = self._points_history.get(code or 0, {})
            recent = [history[gw] for gw in range(max(1, event - 5), event) if gw in history]
            position = target[0].get("position") or ""
            baselines["zero"][element_id] = 0.0
            baselines["previous_five_mean"][element_id] = mean(recent) if recent else 0.0
            baselines["last_gameweek"][element_id] = history.get(event - 1, 0.0)
            baselines["position_mean"][element_id] = position_mean.get(position, 0.0)
        return baselines

    def snapshot_before(self, event: int) -> Snapshot:
        target_rows = self._target_rows(event)
        cumulative = self.cumulative_before(event)
        elements: list[dict[str, Any]] = []
        total_selected = max(
            1.0,
            max(
                (_float(row.get("selected")) for rows in target_rows.values() for row in rows),
                default=1.0,
            )
            / 0.70,
        )
        for element_id, rows in target_rows.items():
            row = rows[0]
            position = row.get("position") or ""
            team_name = row.get("team") or ""
            if position not in POSITION_IDS or team_name not in self.team_name_to_id:
                continue
            state = cumulative.get(element_id, {})
            elements.append(
                {
                    "id": element_id,
                    "code": self.id_to_code.get(element_id, 0),
                    "web_name": row.get("name") or str(element_id),
                    "first_name": "",
                    "second_name": row.get("name") or str(element_id),
                    "element_type": POSITION_IDS[position],
                    "team": self.team_name_to_id[team_name],
                    "can_select": True,
                    "removed": False,
                    "status": "a",
                    "chance_of_playing_next_round": None,
                    "selected_by_percent": str(
                        round(100.0 * _float(row.get("selected")) / total_selected, 4)
                    ),
                    "now_cost": _int(row.get("value")),
                    "starts": _int(state.get("starts")),
                    "minutes": _int(state.get("minutes")),
                    "expected_goals": state.get("expected_goals", 0.0),
                    "expected_assists": state.get("expected_assists", 0.0),
                    "defensive_contribution": _int(state.get("defensive_contribution")),
                    "saves": _int(state.get("saves")),
                    "bonus": _int(state.get("bonus")),
                    "yellow_cards": _int(state.get("yellow_cards")),
                    "red_cards": _int(state.get("red_cards")),
                    "total_points": _int(state.get("total_points")),
                    "event_points": 0,
                    "expected_goals_conceded": 0.0,
                    "transfers_in_event": _int(row.get("transfers_in")),
                    "transfers_out_event": _int(row.get("transfers_out")),
                    "news": "",
                    "opta_code": None,
                    "penalties_order": None,
                    "direct_freekicks_order": None,
                    "corners_and_indirect_freekicks_order": None,
                }
            )

        team_played: dict[int, int] = defaultdict(int)
        fixtures: list[dict[str, Any]] = []
        kickoff_values: list[datetime] = []
        for row in self.fixtures:
            fixture_event = _int(row.get("event"))
            home_id, away_id = _int(row.get("team_h")), _int(row.get("team_a"))
            is_past = fixture_event < event
            if is_past:
                team_played[home_id] += 1
                team_played[away_id] += 1
            kickoff = row.get("kickoff_time")
            if fixture_event == event and kickoff:
                kickoff_values.append(datetime.fromisoformat(kickoff))
            fixtures.append(
                {
                    "id": _int(row.get("id")),
                    "event": fixture_event,
                    "team_h": home_id,
                    "team_a": away_id,
                    "kickoff_time": kickoff,
                    "team_h_score": _int(row.get("team_h_score")) if is_past else None,
                    "team_a_score": _int(row.get("team_a_score")) if is_past else None,
                    "started": is_past,
                    "finished": is_past,
                }
            )
        teams = []
        for row in self.teams:
            team = dict(row)
            team["id"] = _int(row["id"])
            team["code"] = _int(row["code"])
            team["played"] = team_played[team["id"]]
            for field in (
                "strength_overall_home",
                "strength_overall_away",
                "strength_attack_home",
                "strength_attack_away",
                "strength_defence_home",
                "strength_defence_away",
            ):
                team[field] = _int(row.get(field))
            teams.append(team)
        deadline = min(kickoff_values) - timedelta(days=2) if kickoff_values else datetime.now(UTC)
        bootstrap = {
            "events": [
                {
                    "id": value,
                    "is_current": value == event - 1,
                    "is_next": value == event,
                    "finished": value < event,
                    "deadline_time": (deadline if value == event else deadline - timedelta(days=7)).isoformat(),
                }
                for value in range(1, 39)
            ],
            "elements": elements,
            "teams": teams,
            "element_types": [{"id": value} for value in range(1, 5)],
            "total_players": int(total_selected),
        }
        return Snapshot.from_payloads(bootstrap, fixtures, deadline - timedelta(hours=1))


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + end - 1) / 2.0 + 1.0
        for index in order[start:end]:
            ranks[index] = rank
        start = end
    return ranks


def _spearman(predicted: list[float], actual: list[float]) -> float:
    if len(predicted) < 2:
        return 0.0
    left, right = _ranks(predicted), _ranks(actual)
    left_mean, right_mean = mean(left), mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    denominator = math.sqrt(
        sum((value - left_mean) ** 2 for value in left)
        * sum((value - right_mean) ** 2 for value in right)
    )
    return numerator / denominator if denominator else 0.0


def _ndcg_at_10(predicted: list[float], actual: list[float]) -> float:
    order = sorted(range(len(predicted)), key=predicted.__getitem__, reverse=True)[:10]
    ideal = sorted(range(len(actual)), key=actual.__getitem__, reverse=True)[:10]

    def gain(indices: Iterable[int]) -> float:
        return sum(max(0.0, actual[index]) / math.log2(rank + 2) for rank, index in enumerate(indices))

    ideal_gain = gain(ideal)
    return gain(order) / ideal_gain if ideal_gain else 0.0


def _top_10_overlap(predicted: list[float], actual: list[float]) -> float:
    predicted_top = set(sorted(range(len(predicted)), key=predicted.__getitem__, reverse=True)[:10])
    actual_top = set(sorted(range(len(actual)), key=actual.__getitem__, reverse=True)[:10])
    return len(predicted_top & actual_top) / max(1, min(10, len(actual)))


def _metric_row(
    predicted: list[float],
    actual: list[float],
    intervals: list[tuple[float, float]] | None = None,
) -> dict[str, float]:
    errors = [estimate - observed for estimate, observed in zip(predicted, actual)]
    result = {
        "mae": mean(abs(value) for value in errors),
        "rmse": math.sqrt(mean(value * value for value in errors)),
        "bias": mean(errors),
        "spearman": _spearman(predicted, actual),
        "ndcg_at_10": _ndcg_at_10(predicted, actual),
        "top_10_overlap": _top_10_overlap(predicted, actual),
    }
    if intervals:
        result["interval_coverage"] = mean(
            lower <= observed <= upper
            for (lower, upper), observed in zip(intervals, actual)
        )
        result["mean_interval_width"] = mean(upper - lower for lower, upper in intervals)
    return result


def benchmark_season(
    archive: SeasonArchive,
    priors: dict[str, Any],
    first_event: int = 6,
    last_event: int = 38,
) -> dict[str, Any]:
    per_model: dict[str, dict[str, list[dict[str, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    row_counts = {"all": 0, "starters": 0}
    for event in range(first_event, last_event + 1):
        snapshot = archive.snapshot_before(event)
        prior_variants = {
            "xp_v0_2": (priors, False, True),
            "xp_v0_2_no_prior_season": (
                {"league": {}, "positions": {}, "teams": {}, "players": {}},
                False,
                True,
            ),
            "xp_v0_2_position_priors_only": (
                {
                    "league": {},
                    "positions": priors.get("positions", {}),
                    "teams": {},
                    "players": {},
                },
                False,
                True,
            ),
            "xp_v0_2_flat_team_challenger": (priors, False, False),
            "xp_v0_2_full_team_prior_challenger": (priors, True, True),
            "xp_v0_2_team_priors_only": (
                {
                    "league": priors.get("league", {}),
                    "positions": priors.get("positions", {}),
                    "teams": priors.get("teams", {}),
                    "players": {},
                },
                True,
                True,
            ),
        }
        baselines = archive.simple_baselines(event)
        interval_bounds: dict[str, dict[int, tuple[float, float]]] = {}
        for name, (variant, use_team_priors, use_ordinal_strength) in prior_variants.items():
            model_rows = ExpectedPointsModel(
                    priors=variant,
                    use_team_priors=use_team_priors,
                    use_ordinal_strength=use_ordinal_strength,
                ).predict(snapshot, event)
            baselines[name] = {row.player_id: row.expected_points for row in model_rows}
            interval_bounds[name] = {
                row.player_id: (row.lower_bound, row.upper_bound) for row in model_rows
            }
        actuals = archive.actuals(event)
        for cohort, eligible in (
            ("all", list(actuals)),
            ("starters", [key for key, value in actuals.items() if value.starts > 0]),
        ):
            row_counts[cohort] += len(eligible)
            for name, estimates in baselines.items():
                keys = [key for key in eligible if key in estimates]
                if not keys:
                    continue
                values = [estimates[key] for key in keys]
                observed = [actuals[key].points for key in keys]
                bounds = interval_bounds.get(name)
                intervals = [bounds[key] for key in keys] if bounds else None
                per_model[name][cohort].append(_metric_row(values, observed, intervals))

    models: dict[str, Any] = {}
    for name, cohorts in per_model.items():
        models[name] = {}
        for cohort, rows in cohorts.items():
            models[name][cohort] = {
                metric: round(mean(row[metric] for row in rows), 6)
                for metric in rows[0]
            }
            models[name][cohort]["gameweeks"] = len(rows)
    return {
        "protocol": {
            "season": archive.season_dir.name,
            "events": [first_event, last_event],
            "information_cutoff": "only gameweeks strictly before the forecast event",
            "aggregation": "metrics calculated within gameweek, then averaged",
            "archive_fpl_xp_warning": "included for reference; exact capture timing is not verified",
        },
        "row_counts": row_counts,
        "models": models,
    }


def write_benchmark_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
