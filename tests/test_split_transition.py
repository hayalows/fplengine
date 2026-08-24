from __future__ import annotations

import unittest

from fplengine.role_transition import TransitionProfile
from fplengine.split_transition_benchmark import split_role_weights


class SplitTransitionTests(unittest.TestCase):
    def test_club_and_promotion_weights_are_independent(self) -> None:
        profiles = {
            1: TransitionProfile(1, "A", "A", True, False, False, False),
            2: TransitionProfile(2, "B", "A", False, True, False, False),
            3: TransitionProfile(3, "C", None, False, False, True, True),
            4: TransitionProfile(4, "D", "A", False, True, False, True),
        }
        weights = split_role_weights(
            profiles,
            club_change_weight=0.25,
            promoted_weight=0.75,
        )
        self.assertNotIn(1, weights)
        self.assertEqual(weights[2], 0.25)
        self.assertEqual(weights[3], 0.75)
        self.assertEqual(weights[4], 0.25)

    def test_invalid_weights_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "\[0, 1\]"):
            split_role_weights({}, club_change_weight=-0.1, promoted_weight=1.0)


if __name__ == "__main__":
    unittest.main()
