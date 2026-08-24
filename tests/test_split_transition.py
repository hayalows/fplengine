from __future__ import annotations

import unittest
from pathlib import Path

from fplengine.role_transition import TransitionProfile
from fplengine.split_transition_benchmark import (
    profile_signature,
    run_split_transition_experiment,
    split_cohort_labels,
    split_role_weights,
)


def _profile(
    code: int,
    *,
    same_club: bool = False,
    club_change: bool = False,
    new_to_fpl: bool = False,
    promoted_team: bool = False,
) -> TransitionProfile:
    prior_team = "A" if not new_to_fpl else None
    target = "A" if same_club else "B"
    return TransitionProfile(
        code,
        target,
        prior_team,
        same_club,
        club_change,
        new_to_fpl,
        promoted_team,
    )


class SplitTransitionTests(unittest.TestCase):
    def test_club_and_promotion_weights_compose_multiplicatively(self) -> None:
        profiles = {
            1: _profile(1, same_club=True),
            2: _profile(2, club_change=True),
            3: _profile(3, new_to_fpl=True, promoted_team=True),
            4: _profile(4, club_change=True, promoted_team=True),
        }
        weights = split_role_weights(
            profiles,
            club_change_weight=0.25,
            promoted_weight=0.5,
        )
        self.assertNotIn(1, weights)
        self.assertEqual(weights[2], 0.25)
        self.assertEqual(weights[3], 0.5)
        self.assertEqual(weights[4], 0.125)

    def test_promoted_weight_of_one_preserves_plain_club_decay(self) -> None:
        profiles = {
            2: _profile(2, club_change=True),
            4: _profile(4, club_change=True, promoted_team=True),
        }
        weights = split_role_weights(
            profiles,
            club_change_weight=0.5,
            promoted_weight=1.0,
        )
        self.assertEqual(weights[2], 0.5)
        self.assertEqual(weights[4], 0.5)

    def test_invalid_weights_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            split_role_weights({}, club_change_weight=-0.1, promoted_weight=1.0)
        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            split_role_weights({}, club_change_weight=1.1, promoted_weight=0.5)

    def test_transfer_subcohorts_are_separated(self) -> None:
        established = split_cohort_labels(_profile(2, club_change=True))
        to_promoted = split_cohort_labels(_profile(4, club_change=True, promoted_team=True))
        self.assertIn("transfer_established", established)
        self.assertNotIn("transfer_to_promoted", established)
        self.assertIn("transfer_to_promoted", to_promoted)
        self.assertIn("club_change", to_promoted)

    def test_profile_signature_reports_evidence_groups(self) -> None:
        signature = profile_signature(_profile(3, new_to_fpl=True, promoted_team=True))
        self.assertEqual(signature, "new_to_fpl+promoted_team")
        self.assertEqual(profile_signature(_profile(1, same_club=True)), "same_club")

    def test_prior_seasons_must_precede_target_season(self) -> None:
        with self.assertRaisesRegex(ValueError, "must precede"):
            run_split_transition_experiment(
                Path("does-not-exist"),
                target_season="2025-26",
                prior_seasons=("2024-25", "2025-26"),
            )
        with self.assertRaisesRegex(ValueError, "At least one prior season"):
            run_split_transition_experiment(
                Path("does-not-exist"),
                target_season="2025-26",
                prior_seasons=(),
            )


if __name__ == "__main__":
    unittest.main()
