"""Interval-calibration challenger: widen upper tails without moving any mean.

The split-transition artifact showed starter undercoverage is a global upper-tail
problem (starter coverage ~0.71-0.76 across every pre-season cohort, including
same-club players) while all-player coverage is healthy. This challenger therefore
inflates the distance from expected points to the upper bound only. Expected points,
expected minutes, ordering, lower bounds and reported risk stay bit-identical, so any
coverage change is attributable to the single widened lever.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .role_transition import RoleTransitionExpectedPointsModel, TransitionProfile


def compose_upper_multipliers(
    profiles: dict[int, TransitionProfile],
    *,
    scope: str,
    factor: float,
    global_factor: float = 1.0,
) -> dict[int, float]:
    """Build per-player upper-tail multipliers from a global and a targeted factor.

    The targeted factor applies to the requested transition scope on top of the
    global factor, so ``scope="none"`` with ``global_factor=f`` widens everyone by
    ``f`` while ``scope="club_change"`` widens transfers by ``global*factor`` and
    everybody else by ``global_factor``.
    """
    if not 1.0 <= global_factor <= 4.0 or not 1.0 <= factor <= 4.0:
        raise ValueError("upper multipliers must be in [1, 4]")
    scopes = ("none", "club_change", "all_transitions")
    if scope not in scopes:
        raise ValueError(f"scope must be one of {scopes}")
    result: dict[int, float] = {}
    for code, profile in profiles.items():
        multiplier = global_factor
        selected = False
        if scope == "club_change":
            selected = profile.club_change
        elif scope == "all_transitions":
            selected = profile.transition
        if selected:
            multiplier *= factor
        result[code] = multiplier
    return result


class IntervalCalibrationExpectedPointsModel(RoleTransitionExpectedPointsModel):
    """Challenger that scales only the upper-bound tail distance per player."""

    def __init__(
        self,
        *,
        priors: dict[str, Any],
        upper_multipliers: dict[int, float] | None = None,
        model_version: str = "xp-v0.3-interval-calibration-challenger",
    ) -> None:
        super().__init__(priors=priors, model_version=model_version)
        self.upper_multipliers = upper_multipliers or {}

    def _player_multiplier(self, player_code: int) -> float:
        value = self.upper_multipliers.get(int(player_code), 1.0)
        return min(4.0, max(1.0, float(value)))

    def predict(self, snapshot: Any, target_event: int | None = None):
        predictions = super().predict(snapshot, target_event)
        if not self.upper_multipliers:
            return predictions
        adjusted = []
        for row in predictions:
            factor = self._player_multiplier(row.player_code)
            if factor == 1.0:
                adjusted.append(row)
                continue
            mid = row.expected_points
            upper = round(mid + (row.upper_bound - mid) * factor, 2)
            adjusted.append(replace(row, upper_bound=upper))
        # Ordering is unchanged because expected_points is untouched; re-sorting only
        # guards against future changes in the parent implementation.
        return sorted(adjusted, key=lambda row: row.expected_points, reverse=True)
