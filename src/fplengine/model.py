"""Transparent expected-points baseline for FPL Engine v0.1.

This is deliberately a calibrated baseline, not a black box. Every component can be
inspected and later replaced by a trained, as-of-safe model.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from .api_client import Snapshot


MODEL_VERSION = "xp-v0.1.0"
POSITION_NAMES = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
GOAL_POINTS = {1: 10, 2: 6, 3: 5, 4: 4}
CLEAN_SHEET_POINTS = {1: 4, 2: 4, 3: 1, 4: 0}
PRIOR_XG90 = {1: 0.0, 2: 0.055, 3: 0.20, 4: 0.36}
PRIOR_XA90 = {1: 0.005, 2: 0.085, 3: 0.17, 4: 0.13}
PRIOR_DC90 = {1: 0.0, 2: 7.5, 3: 6.5, 4: 2.8}
DEFAULT_START_MINUTES = {1: 90.0, 2: 82.0, 3: 76.0, 4: 75.0}
COST_RANGES = {1: (40, 60), 2: (40, 75), 3: (45, 150), 4: (45, 150)}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _poisson_tail(rate: float, threshold: int) -> float:
    if rate <= 0:
        return 0.0
    probability_below = 0.0
    term = math.exp(-rate)
    probability_below += term
    for count in range(1, threshold):
        term *= rate / count
        probability_below += term
    return _clamp(1.0 - probability_below, 0.0, 1.0)


def _expected_goal_conceded_deductions(rate: float) -> float:
    """E[floor(goals / 2)] for a Poisson score, truncated safely at 14 goals."""
    if rate <= 0:
        return 0.0
    probability = math.exp(-rate)
    expected = 0.0
    for goals in range(1, 15):
        probability *= rate / goals
        expected += (goals // 2) * probability
    return expected


@dataclass(frozen=True)
class Prediction:
    player_id: int
    player_code: int
    player_name: str
    team_id: int
    team: str
    position: str
    price: float
    ownership_percent: float
    target_event: int
    fixture_count: int
    expected_minutes: float
    expected_points: float
    expected_goals: float
    expected_assists: float
    clean_sheet_probability: float
    risk: float
    confidence: str
    value_score: float
    differential_score: float
    market_net_transfers: int
    market_momentum_percent: float
    lower_bound: float
    upper_bound: float
    model_version: str
    data_as_of: str
    components: dict[str, float]
    provenance: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExpectedPointsModel:
    def __init__(self, model_version: str = MODEL_VERSION) -> None:
        self.model_version = model_version

    @staticmethod
    def _availability(player: dict[str, Any]) -> float:
        if not player.get("can_select", True) or player.get("removed"):
            return 0.0
        status = player.get("status", "a")
        if status in {"i", "s", "u", "n"}:
            return 0.0
        chance = player.get("chance_of_playing_next_round")
        if chance is not None:
            return _clamp(_number(chance) / 100.0, 0.0, 1.0)
        return 1.0 if status == "a" else 0.75

    @staticmethod
    def _minutes_projection(player: dict[str, Any], team_played: int) -> tuple[float, float, float]:
        position = int(player["element_type"])
        ownership = _clamp(_number(player.get("selected_by_percent")), 0.0, 100.0)
        low_cost, high_cost = COST_RANGES[position]
        cost_signal = _clamp((int(player["now_cost"]) - low_cost) / (high_cost - low_cost), 0.0, 1.0)
        ownership_signal = _clamp(math.log1p(ownership) / math.log1p(35.0), 0.0, 1.0)
        set_piece_signal = 1.0 if any(
            player.get(key)
            for key in (
                "penalties_order",
                "direct_freekicks_order",
                "corners_and_indirect_freekicks_order",
            )
        ) else 0.0
        prior_start = _clamp(0.22 + 0.48 * ownership_signal + 0.20 * cost_signal + 0.08 * set_piece_signal, 0.12, 0.96)
        starts = max(0.0, _number(player.get("starts")))
        played = max(0, int(team_played))
        start_probability = (starts + 3.0 * prior_start) / (played + 3.0)
        if played and starts == 0:
            start_probability *= 0.72
        minutes = max(0.0, _number(player.get("minutes")))
        minutes_per_start = (
            minutes + 2.0 * DEFAULT_START_MINUTES[position]
        ) / (starts + 2.0)
        availability = ExpectedPointsModel._availability(player)
        cameo_probability = 0.40 if position != 1 else 0.03
        expected_minutes = availability * (
            start_probability * minutes_per_start
            + (1.0 - start_probability) * cameo_probability * 14.0
        )
        return _clamp(expected_minutes, 0.0, 90.0), _clamp(start_probability, 0.0, 1.0), availability

    @staticmethod
    def _shrunk_rate(player: dict[str, Any], field: str, prior: float) -> float:
        minutes = max(0.0, _number(player.get("minutes")))
        observed_total = max(0.0, _number(player.get(field)))
        prior_minutes = 450.0
        return 90.0 * (observed_total + prior * prior_minutes / 90.0) / (minutes + prior_minutes)

    @staticmethod
    def _team_goal_rates(
        home: dict[str, Any], away: dict[str, Any]
    ) -> tuple[float, float]:
        # FPL strength fields are calculated third-party inputs, not observed match facts.
        home_attack = max(1.0, _number(home.get("strength_attack_home"), 1000.0))
        away_attack = max(1.0, _number(away.get("strength_attack_away"), 1000.0))
        home_defence = max(1.0, _number(home.get("strength_defence_home"), 1000.0))
        away_defence = max(1.0, _number(away.get("strength_defence_away"), 1000.0))
        home_xg = 1.55 * (home_attack / 1000.0) * (1000.0 / away_defence)
        away_xg = 1.25 * (away_attack / 1000.0) * (1000.0 / home_defence)
        return _clamp(home_xg, 0.25, 3.25), _clamp(away_xg, 0.20, 3.00)

    def predict(self, snapshot: Snapshot, target_event: int | None = None) -> list[Prediction]:
        event_id = snapshot.target_event(target_event)
        snapshot.event(event_id)
        teams = {int(row["id"]): row for row in snapshot.bootstrap["teams"]}
        players = [row for row in snapshot.bootstrap["elements"] if row.get("can_select", True)]
        players_by_team: dict[int, list[dict[str, Any]]] = {}
        for player in players:
            players_by_team.setdefault(int(player["team"]), []).append(player)

        minute_state: dict[int, tuple[float, float, float]] = {}
        rate_state: dict[int, tuple[float, float, float]] = {}
        observed_team_matches = {
            team_id: max(
                int(teams[team_id].get("played") or 0),
                max((int(row.get("starts") or 0) for row in squad), default=0),
            )
            for team_id, squad in players_by_team.items()
        }
        for player in players:
            player_id = int(player["id"])
            position = int(player["element_type"])
            minute_state[player_id] = self._minutes_projection(
                player, observed_team_matches.get(int(player["team"]), 0)
            )
            rate_state[player_id] = (
                self._shrunk_rate(player, "expected_goals", PRIOR_XG90[position]),
                self._shrunk_rate(player, "expected_assists", PRIOR_XA90[position]),
                self._shrunk_rate(player, "defensive_contribution", PRIOR_DC90[position]),
            )

        accumulators: dict[int, dict[str, float]] = {
            int(player["id"]): {
                "appearance": 0.0,
                "goals": 0.0,
                "assists": 0.0,
                "clean_sheet": 0.0,
                "saves": 0.0,
                "defensive_contribution": 0.0,
                "bonus": 0.0,
                "goals_conceded": 0.0,
                "cards": 0.0,
                "expected_goals": 0.0,
                "expected_assists": 0.0,
                "cs_probability_sum": 0.0,
                "fixtures": 0.0,
                "minutes": 0.0,
            }
            for player in players
        }

        target_fixtures = [
            row for row in snapshot.fixtures if row.get("event") == event_id and not row.get("finished")
        ]
        for fixture in target_fixtures:
            home_id, away_id = int(fixture["team_h"]), int(fixture["team_a"])
            home_xg, away_xg = self._team_goal_rates(teams[home_id], teams[away_id])
            for team_id, team_xg, opponent_xg in (
                (home_id, home_xg, away_xg),
                (away_id, away_xg, home_xg),
            ):
                squad = players_by_team.get(team_id, [])
                goal_weights: dict[int, float] = {}
                assist_weights: dict[int, float] = {}
                for player in squad:
                    player_id = int(player["id"])
                    expected_minutes, _, _ = minute_state[player_id]
                    xg90, xa90, _ = rate_state[player_id]
                    goal_weights[player_id] = max(0.0, xg90 * expected_minutes / 90.0)
                    assist_weights[player_id] = max(0.0, xa90 * expected_minutes / 90.0)
                goal_total = sum(goal_weights.values())
                assist_total = sum(assist_weights.values())

                for player in squad:
                    player_id = int(player["id"])
                    position = int(player["element_type"])
                    expected_minutes, start_probability, _ = minute_state[player_id]
                    _, _, dc90 = rate_state[player_id]
                    p_play = _clamp(expected_minutes / 25.0, 0.0, 1.0)
                    p_60 = _clamp((expected_minutes - 30.0) / 35.0, 0.0, 1.0)
                    appearance = p_play + p_60
                    expected_goals = (
                        team_xg * 0.86 * goal_weights[player_id] / goal_total if goal_total else 0.0
                    )
                    expected_assists = (
                        team_xg * 0.74 * assist_weights[player_id] / assist_total
                        if assist_total
                        else 0.0
                    )
                    clean_sheet_probability = math.exp(-opponent_xg)
                    clean_sheet = CLEAN_SHEET_POINTS[position] * p_60 * clean_sheet_probability
                    saves = 0.0
                    if position == 1:
                        saves90 = self._shrunk_rate(player, "saves", 3.0)
                        saves = (saves90 * expected_minutes / 90.0) / 3.0
                    threshold = 10 if position == 2 else 12
                    dc_points = 0.0 if position == 1 else 2.0 * _poisson_tail(
                        dc90 * expected_minutes / 90.0, threshold
                    )
                    conceded = 0.0
                    if position in {1, 2}:
                        conceded = -p_60 * _expected_goal_conceded_deductions(opponent_xg)
                    attacking_returns = expected_goals + expected_assists
                    bonus = start_probability * _clamp(
                        0.25 + 0.55 * attacking_returns + 0.18 * clean_sheet_probability,
                        0.0,
                        1.25,
                    )
                    minutes_seen = max(0.0, _number(player.get("minutes")))
                    yellow_rate = (_number(player.get("yellow_cards")) + 0.10) / (minutes_seen + 900.0)
                    red_rate = (_number(player.get("red_cards")) + 0.01) / (minutes_seen + 1800.0)
                    cards = -expected_minutes * yellow_rate - 3.0 * expected_minutes * red_rate

                    acc = accumulators[player_id]
                    acc["appearance"] += appearance
                    acc["goals"] += GOAL_POINTS[position] * expected_goals
                    acc["assists"] += 3.0 * expected_assists
                    acc["clean_sheet"] += clean_sheet
                    acc["saves"] += saves
                    acc["defensive_contribution"] += dc_points
                    acc["bonus"] += bonus
                    acc["goals_conceded"] += conceded
                    acc["cards"] += cards
                    acc["expected_goals"] += expected_goals
                    acc["expected_assists"] += expected_assists
                    acc["cs_probability_sum"] += clean_sheet_probability
                    acc["fixtures"] += 1.0
                    acc["minutes"] += expected_minutes

        total_players = max(1, int(snapshot.bootstrap.get("total_players") or 1))
        predictions: list[Prediction] = []
        for player in players:
            player_id = int(player["id"])
            position = int(player["element_type"])
            team = teams[int(player["team"])]
            expected_minutes, start_probability, availability = minute_state[player_id]
            acc = accumulators[player_id]
            components = {
                key: round(value, 4)
                for key, value in acc.items()
                if key
                in {
                    "appearance",
                    "goals",
                    "assists",
                    "clean_sheet",
                    "saves",
                    "defensive_contribution",
                    "bonus",
                    "goals_conceded",
                    "cards",
                }
            }
            expected_points = sum(components.values())
            fixture_count = int(acc["fixtures"])
            risk = _clamp(1.0 - availability * (0.72 * start_probability + 0.28 * min(1.0, expected_minutes / 70.0)), 0.0, 1.0)
            team_played = observed_team_matches.get(int(player["team"]), 0)
            if team_played >= 6 and _number(player.get("minutes")) >= 360:
                confidence = "medium"
            else:
                confidence = "low"
            price = int(player["now_cost"]) / 10.0
            ownership = _number(player.get("selected_by_percent"))
            net_transfers = int(player.get("transfers_in_event") or 0) - int(
                player.get("transfers_out_event") or 0
            )
            selected_count = max(1000.0, total_players * ownership / 100.0)
            momentum = 100.0 * net_transfers / selected_count
            value_score = expected_points / price if price else 0.0
            differential_score = expected_points * math.sqrt(max(0.0, 1.0 - ownership / 100.0))
            uncertainty = 2.0 + 1.25 * math.sqrt(max(0.0, acc["expected_goals"] + acc["expected_assists"])) + 2.2 * risk
            predictions.append(
                Prediction(
                    player_id=player_id,
                    player_code=int(player.get("code") or 0),
                    player_name=str(player["web_name"]),
                    team_id=int(player["team"]),
                    team=str(team["short_name"]),
                    position=POSITION_NAMES[position],
                    price=price,
                    ownership_percent=round(ownership, 2),
                    target_event=event_id,
                    fixture_count=fixture_count,
                    expected_minutes=round(acc["minutes"], 2),
                    expected_points=round(expected_points, 3),
                    expected_goals=round(acc["expected_goals"], 3),
                    expected_assists=round(acc["expected_assists"], 3),
                    clean_sheet_probability=round(
                        acc["cs_probability_sum"] / fixture_count if fixture_count else 0.0, 4
                    ),
                    risk=round(risk, 4),
                    confidence=confidence,
                    value_score=round(value_score, 4),
                    differential_score=round(differential_score, 4),
                    market_net_transfers=net_transfers,
                    market_momentum_percent=round(momentum, 4),
                    lower_bound=round(max(-2.0, expected_points - 1.10 * uncertainty), 2),
                    upper_bound=round(expected_points + 1.60 * uncertainty, 2),
                    model_version=self.model_version,
                    data_as_of=snapshot.fetched_at.isoformat(),
                    components=components,
                    provenance={
                        "observed": "FPL bootstrap player totals, availability, ownership and transfers",
                        "third_party": "FPL team strength ratings and fixture difficulty context",
                        "calculated": "minutes, team goal rates, component xP, risk and uncertainty",
                        "prediction": f"expected FPL points for GW{event_id}",
                        "assumptions": "early-season position priors; Poisson team goals; shrunk player rates",
                    },
                )
            )
        return sorted(predictions, key=lambda row: row.expected_points, reverse=True)
