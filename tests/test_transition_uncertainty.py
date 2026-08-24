from __future__ import annotations

import unittest
from pathlib import Path

from fplengine.role_transition import TransitionProfile
from fplengine.transition_uncertainty import (
    IntervalCalibrationExpectedPointsModel,
    compose_upper_multipliers,
)
from .helpers import snapshot


def _profiles() -> dict[int, TransitionProfile]:
    return {
        1: TransitionProfile(1, "A", "A", True, False, False, False),
        2: TransitionProfile(2, "B", "A", False, True, False, False),
        3: TransitionProfile(3, "C", None, False, False, True, True),
        4: TransitionProfile(4, "D", "A", False, True, False, True),
    }


class ComposeUpperMultipliersTests(unittest.TestCase):
    def test_global_factor_applies_to_every_player(self) -> None:
        multipliers = compose_upper_multipliers(
            _profiles(), scope="none", factor=1.0, global_factor=1.5
        )
        self.assertEqual(set(multipliers), {1, 2, 3, 4})
        self.assertEqual(set(multipliers.values()), {1.5})

    def test_targeted_scope_composes_multiplicatively(self) -> None:
        multipliers = compose_upper_multipliers(
            _profiles(), scope="club_change", factor=1.5, global_factor=1.25
        )
        self.assertEqual(multipliers[1], 1.25)
        self.assertEqual(multipliers[2], 1.875)
        self.assertEqual(multipliers[3], 1.25)
        self.assertEqual(multipliers[4], 1.875)

    def test_invalid_factors_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, r"\[1, 4\]"):
            compose_upper_multipliers(_profiles(), scope="none", factor=0.5)
        with self.assertRaisesRegex(ValueError, "scope must be"):
            compose_upper_multipliers(_profiles(), scope="everything", factor=1.0)


class IntervalCalibrationModelTests(unittest.TestCase):
    def test_only_upper_bounds_move_and_ordering_is_stable(self) -> None:
        snap = snapshot()
        baseline = IntervalCalibrationExpectedPointsModel(priors={}).predict(snap, 3)
        widened = IntervalCalibrationExpectedPointsModel(
            priors={},
            upper_multipliers={code: 2.0 for code in range(1, 6)},
        ).predict(snap, 3)
        self.assertEqual(
            [row.expected_points for row in baseline],
            [row.expected_points for row in widened],
        )
        self.assertEqual([row.player_id for row in baseline], [row.player_id for row in widened])
        for before, after in zip(baseline, widened):
            self.assertEqual(before.lower_bound, after.lower_bound)
            self.assertEqual(before.risk, after.risk)
            self.assertEqual(before.expected_minutes, after.expected_minutes)
            if after.upper_bound > after.expected_points:
                self.assertGreaterEqual(after.upper_bound, before.upper_bound)

    def test_missing_multiplier_leaves_row_untouched(self) -> None:
        snap = snapshot()
        baseline = IntervalCalibrationExpectedPointsModel(priors={}).predict(snap, 3)
        widened = IntervalCalibrationExpectedPointsModel(
            priors={}, upper_multipliers={999999: 2.0}
        ).predict(snap, 3)
        self.assertEqual(baseline, widened)

    def test_prior_seasons_must_precede_target_season(self) -> None:
        from fplengine.interval_calibration_benchmark import run_interval_calibration_experiment

        with self.assertRaisesRegex(ValueError, "must precede"):
            run_interval_calibration_experiment(
                Path("does-not-exist"),
                target_season="2025-26",
                prior_seasons=("2026-27",),
            )


if __name__ == "__main__":
    unittest.main()
