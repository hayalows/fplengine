"""History-depth challenger for v0.3 experiments.

The live xp-v0.2.0 model remains unchanged. This subclass understands schema-aware
multi-season priors by using per-field exposure and role-specific opportunities.
"""

from __future__ import annotations

from typing import Any

from .model import ExpectedPointsModel, POSITION_NAMES, _number


class HistoricalExpectedPointsModel(ExpectedPointsModel):
    """Expected-points challenger that can safely consume heterogeneous seasons."""

    def __init__(
        self,
        *,
        priors: dict[str, Any],
        model_version: str = "xp-v0.3-history-challenger",
        use_team_priors: bool = False,
        use_ordinal_strength: bool = True,
    ) -> None:
        super().__init__(
            model_version=model_version,
            priors=priors,
            use_team_priors=use_team_priors,
            use_ordinal_strength=use_ordinal_strength,
        )

    def _player_prior(self, player: dict[str, Any]) -> dict[str, Any]:
        prior = super()._player_prior(player)
        role_opportunities = _number(prior.get("starts_opportunities"))
        if role_opportunities <= 0:
            return prior
        # v0.2 interprets `games` as the denominator for starts/cameos. In the
        # historical schema, only seasons that actually expose `starts` are allowed into
        # that denominator. Older seasons still contribute to fields they did measure.
        adjusted = dict(prior)
        adjusted["games"] = role_opportunities
        return adjusted

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
        prior = super()._player_prior(player)
        historical_minutes = max(
            0.0,
            _number(
                prior.get(
                    f"{prior_field}_minutes",
                    prior.get("minutes"),
                )
            ),
        )
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

    def provenance_label(self) -> str:
        seasons = self.priors.get("source_seasons", [])
        decay = self.priors.get("decay")
        return (
            f"schema-aware historical prior: {','.join(map(str, seasons))}; decay={decay}"
            if seasons
            else "schema-aware historical prior"
        )
