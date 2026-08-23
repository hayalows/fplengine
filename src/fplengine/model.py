"""Transparent, prior-informed expected-points model for FPL Engine v0.2.

This is deliberately a transparent challenger, not a black box. Every component can be
inspected and later replaced by a trained, as-of-safe model.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from .api_client import Snapshot
from .priors import load_default_priors

MODEL_VERSION = "xp-v0.2.0"
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
class MinutesProjection:
    expected_minutes: float
    start_probability: float
    appearance_probability: float
    sixty_probability: float
    availability: float
    starter_minutes: float
    risk: float


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
    def __init__(
        self,
        model_version: str = MODEL_VERSION,
        priors: dict[str, Any] | None = None,
        use_team_priors: bool = False,
        use_ordinal_strength: bool = True,
    ) -> None:
        self.model_version = model_version
        self.priors = priors if priors is not None else load_default_priors()
        self.use_team_priors = use_team_priors
        self.use_ordinal_strength = use_ordinal_strength

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

    def _position_prior(self, position: int, field: str, fallback: float) -> float:
        return _number(
            self.priors.get("positions", {}).get(POSITION_NAMES[position], {}).get(field),
            fallback,
        )

    def _player_prior(self, player: dict[str, Any]) -> dict[str, Any]:
        code = str(int(player.get("code") or 0))
        return self.priors.get("players", {}).get(code, {})

    def _minutes_projection(self, player: dict[str, Any], team_played: int) -> MinutesProjection:
        position = int(player["element_type"])
        prior = self._player_prior(player)
        position_prior = self.priors.get("positions", {}).get(POSITION_NAMES[position], {})
        low_cost, high_cost = COST_RANGES[position]
        cost_signal = _clamp(
            (int(player["now_cost"]) - low_cost) / (high_cost - low_cost), 0.0, 1.0
        )
        set_piece_signal = 1.0 if any(
            player.get(key)
            for key in (
                "penalties_order",
                "direct_freekicks_order",
                "corners_and_indirect_freekicks_order",
            )
        ) else 0.0
        generic_start = _number(position_prior.get("start_rate"), 0.36)
        prior_games = max(0.0, _number(prior.get("games")))
        if prior_games:
            prior_start = (_number(prior.get("starts")) + 1.5) / (prior_games + 3.0)
            prior_weight = _clamp(prior_games / 6.0, 2.0, 6.0)
        else:
            prior_start = _clamp(
                generic_start + 0.18 * (cost_signal - 0.5) + 0.06 * set_piece_signal,
                0.12,
                0.88,
            )
            prior_weight = 2.0
        starts = max(0.0, _number(player.get("starts")))
        played = max(0, int(team_played))
        current_weight = 2.0
        start_probability = (
            current_weight * starts + prior_weight * prior_start
        ) / (current_weight * played + prior_weight)
        minutes = max(0.0, _number(player.get("minutes")))
        prior_starts = max(0.0, _number(prior.get("starts")))
        prior_starter_minutes = (
            _number(prior.get("starter_minutes")) / prior_starts
            if prior_starts
            else _number(position_prior.get("starter_minutes"), DEFAULT_START_MINUTES[position])
        )
        current_starter_minutes = min(90.0, minutes / starts) if starts else prior_starter_minutes
        minutes_per_start = (
            current_weight * starts * current_starter_minutes
            + prior_weight * prior_starter_minutes
        ) / max(1.0, current_weight * starts + prior_weight)
        prior_nonstarts = max(1.0, prior_games - prior_starts)
        cameo_probability = (
            _number(prior.get("substitute_appearances")) / prior_nonstarts
            if prior_games
            else _number(position_prior.get("cameo_rate"), 0.30 if position != 1 else 0.02)
        )
        substitute_appearances = max(0.0, _number(prior.get("substitute_appearances")))
        cameo_minutes = (
            _number(prior.get("substitute_minutes")) / substitute_appearances
            if substitute_appearances
            else _number(position_prior.get("cameo_minutes"), 14.0)
        )
        availability = ExpectedPointsModel._availability(player)
        expected_minutes = availability * (
            start_probability * minutes_per_start
            + (1.0 - start_probability) * cameo_probability * cameo_minutes
        )
        appearance_probability = availability * (
            start_probability + (1.0 - start_probability) * cameo_probability
        )
        sixty_given_start = _clamp((minutes_per_start - 45.0) / 20.0, 0.10, 1.0)
        sixty_probability = availability * start_probability * sixty_given_start
        risk = 1.0 - (0.75 * appearance_probability + 0.25 * sixty_probability)
        return MinutesProjection(
            expected_minutes=_clamp(expected_minutes, 0.0, 90.0),
            start_probability=_clamp(start_probability, 0.0, 1.0),
            appearance_probability=_clamp(appearance_probability, 0.0, 1.0),
            sixty_probability=_clamp(sixty_probability, 0.0, 1.0),
            availability=availability,
            starter_minutes=_clamp(minutes_per_start, 0.0, 90.0),
            risk=_clamp(risk, 0.0, 1.0),
        )

    def _posterior_rate(
        self,
        player: dict[str, Any],
        field: str,
        prior_field: str,
        position_field: str,
        fallback: float,
        prior_minutes: float = 900.0,
    ) -> float:
        position = int(player["element_type"])
        position_rate = self._position_prior(position, position_field, fallback)
        prior = self._player_prior(player)
        historical_minutes = max(0.0, _number(prior.get("minutes")))
        historical_total = max(0.0, _number(prior.get(prior_field)))
        historical_rate = 90.0 * (
            historical_total + position_rate * prior_minutes / 90.0
        ) / (historical_minutes + prior_minutes)
        current_minutes = max(0.0, _number(player.get("minutes")))
        current_total = max(0.0, _number(player.get(field)))
        current_prior_minutes = 675.0
        return 90.0 * (
            current_total + historical_rate * current_prior_minutes / 90.0
        ) / (current_minutes + current_prior_minutes)

    def _team_factor(
        self,
        team: dict[str, Any],
        venue: str,
        kind: str,
        league_rate: float,
    ) -> float:
        prior = (
            self.priors.get("teams", {}).get(str(team.get("name")), {})
            if self.use_team_priors
            else {}
        )
        matches = max(0.0, _number(prior.get(f"{venue}_matches")))
        field = f"{venue}_xg_{'for' if kind == 'attack' else 'against'}"
        if matches:
            evidence_rate = (
                _number(prior.get(field)) + 6.0 * league_rate
            ) / (matches + 6.0)
            evidence_factor = evidence_rate / league_rate
        else:
            evidence_factor = 0.84 if kind == "attack" else 1.16

        ordinal = (
            _number(team.get(f"strength_overall_{venue}"), 3.0)
            if self.use_ordinal_strength
            else 3.0
        )
        ordinal_strength = _clamp(1.0 + 0.08 * (ordinal - 3.0), 0.80, 1.20)
        ordinal_factor = ordinal_strength if kind == "attack" else 1.0 / ordinal_strength
        evidence_weight = 0.85 if matches else 0.35
        return evidence_weight * evidence_factor + (1.0 - evidence_weight) * ordinal_factor

    def _team_goal_rates(
        self, home: dict[str, Any], away: dict[str, Any]
    ) -> tuple[float, float]:
        league = self.priors.get("league", {}) if self.use_team_priors else {}
        home_base = _clamp(_number(league.get("home_xg"), 1.55), 1.1, 2.0)
        away_base = _clamp(_number(league.get("away_xg"), 1.25), 0.9, 1.7)
        home_attack = self._team_factor(home, "home", "attack", home_base)
        away_defence = self._team_factor(away, "away", "defence", home_base)
        away_attack = self._team_factor(away, "away", "attack", away_base)
        home_defence = self._team_factor(home, "home", "defence", away_base)
        home_xg = home_base * home_attack * away_defence
        away_xg = away_base * away_attack * home_defence
        return _clamp(home_xg, 0.35, 3.25), _clamp(away_xg, 0.30, 3.00)

    def predict(self, snapshot: Snapshot, target_event: int | None = None) -> list[Prediction]:
        event_id = snapshot.target_event(target_event)
        snapshot.event(event_id)
        teams = {int(row["id"]): row for row in snapshot.bootstrap["teams"]}
        players = [row for row in snapshot.bootstrap["elements"] if row.get("can_select", True)]
        players_by_team: dict[int, list[dict[str, Any]]] = {}
        for player in players:
            players_by_team.setdefault(int(player["team"]), []).append(player)

        minute_state: dict[int, MinutesProjection] = {}
        rate_state: dict[int, dict[str, float]] = {}
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
            rate_state[player_id] = {
                "xg90": self._posterior_rate(
                    player, "expected_goals", "expected_goals", "xg90", PRIOR_XG90[position]
                ),
                "xa90": self._posterior_rate(
                    player, "expected_assists", "expected_assists", "xa90", PRIOR_XA90[position]
                ),
                "dc90": self._posterior_rate(
                    player,
                    "defensive_contribution",
                    "defensive_contribution",
                    "dc90",
                    PRIOR_DC90[position],
                ),
                "saves90": self._posterior_rate(
                    player, "saves", "saves", "saves90", 3.0 if position == 1 else 0.0
                ),
                "bonus90": self._posterior_rate(
                    player, "bonus", "bonus", "bonus90", 0.35
                ),
                "yellow90": self._posterior_rate(
                    player, "yellow_cards", "yellow_cards", "yellow90", 0.10
                ),
                "red90": self._posterior_rate(
                    player, "red_cards", "red_cards", "red90", 0.008, prior_minutes=1800.0
                ),
            }

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
                "variance": 0.0,
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
                    expected_minutes = minute_state[player_id].expected_minutes
                    xg90 = rate_state[player_id]["xg90"]
                    xa90 = rate_state[player_id]["xa90"]
                    goal_weights[player_id] = max(0.0, xg90 * expected_minutes / 90.0)
                    assist_weights[player_id] = max(0.0, xa90 * expected_minutes / 90.0)
                goal_total = sum(goal_weights.values())
                assist_total = sum(assist_weights.values())

                for player in squad:
                    player_id = int(player["id"])
                    position = int(player["element_type"])
                    minutes_projection = minute_state[player_id]
                    expected_minutes = minutes_projection.expected_minutes
                    p_play = minutes_projection.appearance_probability
                    p_60 = minutes_projection.sixty_probability
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
                        saves90 = rate_state[player_id]["saves90"]
                        saves = (saves90 * expected_minutes / 90.0) / 3.0
                    threshold = 10 if position == 2 else 12
                    dc_points = 0.0 if position == 1 else 2.0 * _poisson_tail(
                        rate_state[player_id]["dc90"] * expected_minutes / 90.0,
                        threshold,
                    )
                    conceded = 0.0
                    if position in {1, 2}:
                        conceded = -p_60 * _expected_goal_conceded_deductions(opponent_xg)
                    bonus = rate_state[player_id]["bonus90"] * expected_minutes / 90.0
                    cards = -rate_state[player_id]["yellow90"] * expected_minutes / 90.0
                    cards -= 3.0 * rate_state[player_id]["red90"] * expected_minutes / 90.0

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
                    cs_award = CLEAN_SHEET_POINTS[position] * p_60
                    acc["variance"] += GOAL_POINTS[position] ** 2 * expected_goals
                    acc["variance"] += 9.0 * expected_assists
                    acc["variance"] += cs_award**2 * clean_sheet_probability * (
                        1.0 - clean_sheet_probability
                    )
                    acc["variance"] += 2.0 * p_play * (1.0 - p_play)

        total_players = max(1, int(snapshot.bootstrap.get("total_players") or 1))
        predictions: list[Prediction] = []
        for player in players:
            player_id = int(player["id"])
            position = int(player["element_type"])
            team = teams[int(player["team"])]
            minutes_projection = minute_state[player_id]
            expected_minutes = minutes_projection.expected_minutes
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
            risk = minutes_projection.risk
            team_played = observed_team_matches.get(int(player["team"]), 0)
            historical_minutes = _number(self._player_prior(player).get("minutes"))
            if team_played >= 10 and _number(player.get("minutes")) >= 600:
                confidence = "high"
            elif historical_minutes >= 900 or (
                team_played >= 6 and _number(player.get("minutes")) >= 360
            ):
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
            uncertainty = math.sqrt(max(1.0, acc["variance"])) + 1.5 * risk
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
                    upper_bound=round(expected_points + 1.28 * uncertainty, 2),
                    model_version=self.model_version,
                    data_as_of=snapshot.fetched_at.isoformat(),
                    components=components,
                    provenance={
                        "observed": "FPL bootstrap player totals, availability, ownership and transfers",
                        "third_party": "FPL fixture context and compact prior-season aggregate evidence",
                        "calculated": "coherent minutes states, opponent-adjusted team rates and component xP",
                        "prediction": f"expected FPL points for GW{event_id}",
                        "assumptions": "hierarchical shrinkage; independent Poisson team goals; role persistence",
                    },
                )
            )
        return sorted(predictions, key=lambda row: row.expected_points, reverse=True)
