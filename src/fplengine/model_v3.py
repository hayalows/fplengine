"""FPL Engine v0.3 candidate: field-aware history and role-transition uncertainty."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from .api_client import Snapshot
from .model import (
    COST_RANGES,
    DEFAULT_START_MINUTES,
    POSITION_NAMES,
    ExpectedPointsModel,
    MinutesProjection,
    Prediction,
    _clamp,
    _number,
)

MODEL_VERSION = "xp-v0.3.0-candidate"


class ExpectedPointsModelV3(ExpectedPointsModel):
    """Transparent challenger that treats role persistence as uncertain evidence."""

    def __init__(
        self,
        *,
        priors: dict[str, Any],
        transition_retention: float = 0.65,
        new_team_retention: float = 0.50,
        current_game_weight: float = 2.5,
        model_version: str = MODEL_VERSION,
    ) -> None:
        super().__init__(
            model_version=model_version,
            priors=priors,
            use_team_priors=False,
            use_ordinal_strength=True,
        )
        self.transition_retention = _clamp(transition_retention, 0.0, 1.0)
        self.new_team_retention = _clamp(new_team_retention, 0.0, 1.0)
        self.current_game_weight = max(0.5, current_game_weight)
        self._current_team_names: dict[int, str] = {}
        self._transition_cache: dict[int, str] = {}

    def _transition_kind(self, player: dict[str, Any]) -> str:
        player_id = int(player.get("id") or 0)
        if player_id in self._transition_cache:
            return self._transition_cache[player_id]
        prior = self._player_prior(player)
        previous_team = str(prior.get("team") or "")
        current_team = self._current_team_names.get(player_id, "")
        current_seen = current_team in self.priors.get("teams", {})
        if not prior:
            kind = "new_or_unmapped"
        elif previous_team and current_team and previous_team != current_team:
            kind = "club_change"
        elif current_team and not current_seen:
            kind = "promoted_or_new_team"
        else:
            kind = "continuity"
        self._transition_cache[player_id] = kind
        return kind

    def _retention(self, player: dict[str, Any]) -> float:
        kind = self._transition_kind(player)
        if kind == "club_change":
            return self.transition_retention
        if kind == "promoted_or_new_team":
            return self.new_team_retention
        if kind == "new_or_unmapped":
            return 0.0
        return 1.0

    def _minutes_projection(self, player: dict[str, Any], team_played: int) -> MinutesProjection:
        position = int(player["element_type"])
        prior = self._player_prior(player)
        position_prior = self.priors.get("positions", {}).get(POSITION_NAMES[position], {})
        retention = self._retention(player)
        low_cost, high_cost = COST_RANGES[position]
        cost_signal = _clamp(
            (int(player["now_cost"]) - low_cost) / max(1, high_cost - low_cost), 0.0, 1.0
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
        generic_start = _clamp(
            generic_start + 0.12 * (cost_signal - 0.5) + 0.04 * set_piece_signal,
            0.08,
            0.92,
        )

        role_games = max(0.0, _number(prior.get("role_games"), prior.get("games", 0.0)))
        prior_starts = max(0.0, _number(prior.get("starts")))
        if role_games > 0:
            observed_start_rate = (prior_starts + 2.0 * generic_start) / (role_games + 2.0)
            prior_start = retention * observed_start_rate + (1.0 - retention) * generic_start
            historical_strength = retention * min(12.0, math.sqrt(role_games) * 2.2)
        else:
            prior_start = generic_start
            historical_strength = 1.5

        starts = max(0.0, _number(player.get("starts")))
        played = max(0.0, float(team_played))
        current_success = self.current_game_weight * starts
        current_trials = self.current_game_weight * played
        start_probability = (
            current_success + historical_strength * prior_start
        ) / max(1e-9, current_trials + historical_strength)

        prior_starter_minutes_total = max(0.0, _number(prior.get("starter_minutes")))
        prior_starter_minutes = (
            prior_starter_minutes_total / max(1.0, prior_starts)
            if prior_starts > 0
            else _number(position_prior.get("starter_minutes"), DEFAULT_START_MINUTES[position])
        )
        minutes = max(0.0, _number(player.get("minutes")))
        current_starter_minutes = min(90.0, minutes / starts) if starts else prior_starter_minutes
        # Duration conditional on starting is more portable than start rate after a transfer.
        duration_retention = 0.85 + 0.15 * retention
        duration_weight = max(1.0, duration_retention * math.sqrt(max(1.0, prior_starts)))
        minutes_per_start = (
            self.current_game_weight * starts * current_starter_minutes
            + duration_weight * prior_starter_minutes
        ) / max(1.0, self.current_game_weight * starts + duration_weight)

        prior_nonstarts = max(1.0, role_games - prior_starts)
        observed_cameo = (
            _number(prior.get("substitute_appearances")) / prior_nonstarts
            if role_games > 0
            else _number(position_prior.get("cameo_rate"), 0.30 if position != 1 else 0.02)
        )
        generic_cameo = _number(position_prior.get("cameo_rate"), 0.30 if position != 1 else 0.02)
        cameo_probability = retention * observed_cameo + (1.0 - retention) * generic_cameo
        sub_apps = max(0.0, _number(prior.get("substitute_appearances")))
        cameo_minutes = (
            _number(prior.get("substitute_minutes")) / sub_apps
            if sub_apps > 0
            else _number(position_prior.get("cameo_minutes"), 14.0)
        )

        availability = self._availability(player)
        expected_minutes = availability * (
            start_probability * minutes_per_start
            + (1.0 - start_probability) * cameo_probability * cameo_minutes
        )
        appearance_probability = availability * (
            start_probability + (1.0 - start_probability) * cameo_probability
        )
        sixty_given_start = _clamp((minutes_per_start - 45.0) / 20.0, 0.08, 1.0)
        sixty_probability = availability * start_probability * sixty_given_start
        sample_uncertainty = math.exp(-0.12 * (played + retention * role_games))
        transition_penalty = 0.16 * (1.0 - retention)
        risk = (
            1.0 - (0.75 * appearance_probability + 0.25 * sixty_probability)
            + 0.10 * sample_uncertainty
            + transition_penalty
        )
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
        retention = self._retention(player)
        evidence_minutes = max(
            0.0,
            _number(prior.get("evidence_minutes", {}).get(prior_field), prior.get("minutes", 0.0)),
        )
        historical_total = max(0.0, _number(prior.get(prior_field)))
        effective_minutes = retention * evidence_minutes
        effective_total = retention * historical_total
        historical_rate = 90.0 * (
            effective_total + position_rate * prior_minutes / 90.0
        ) / max(1e-9, effective_minutes + prior_minutes)
        current_minutes = max(0.0, _number(player.get("minutes")))
        current_total = max(0.0, _number(player.get(field)))
        current_prior_minutes = 675.0
        return 90.0 * (
            current_total + historical_rate * current_prior_minutes / 90.0
        ) / max(1e-9, current_minutes + current_prior_minutes)

    def predict(self, snapshot: Snapshot, target_event: int | None = None) -> list[Prediction]:
        teams = {int(row["id"]): row for row in snapshot.bootstrap["teams"]}
        self._current_team_names = {
            int(player["id"]): str(teams[int(player["team"])].get("name") or "")
            for player in snapshot.bootstrap["elements"]
            if int(player.get("team") or 0) in teams
        }
        self._transition_cache = {}
        rows = super().predict(snapshot, target_event)
        output: list[Prediction] = []
        players = {int(row["id"]): row for row in snapshot.bootstrap["elements"]}
        for row in rows:
            player = players[row.player_id]
            transition = self._transition_kind(player)
            retention = self._retention(player)
            provenance = dict(row.provenance)
            provenance["historical_depth"] = str(self.priors.get("history", {}).get("depth", 1))
            provenance["role_transition"] = transition
            provenance["assumptions"] = (
                "field-aware historical shrinkage; coherent minutes states; "
                f"role retention={retention:.2f}; independent Poisson team goals"
            )
            confidence = row.confidence
            if transition != "continuity" and confidence == "high":
                confidence = "medium"
            if transition in {"new_or_unmapped", "promoted_or_new_team"}:
                confidence = "low"
            extra_width = 0.6 * (1.0 - retention)
            output.append(
                replace(
                    row,
                    confidence=confidence,
                    lower_bound=round(row.lower_bound - extra_width, 2),
                    upper_bound=round(row.upper_bound + extra_width, 2),
                    provenance=provenance,
                )
            )
        return sorted(output, key=lambda row: row.expected_points, reverse=True)
