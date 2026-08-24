from __future__ import annotations

import unittest

from fplengine.role_transition import (
    RoleTransitionExpectedPointsModel,
    TransitionProfile,
    transition_role_weights,
)


class RoleTransitionTests(unittest.TestCase):
    def test_transition_weight_only_scales_role_evidence(self) -> None:
        priors = {
            "positions": {"MID": {"start_rate": 0.5, "xg90": 0.2}},
            "players": {
                "99": {
                    "position": "MID",
                    "team": "Old Club",
                    "games": 20.0,
                    "starts": 16.0,
                    "starts_opportunities": 20.0,
                    "starter_minutes": 1280.0,
                    "substitute_appearances": 2.0,
                    "substitute_minutes": 30.0,
                    "expected_goals": 6.0,
                    "expected_goals_minutes": 1600.0,
                }
            },
        }
        model = RoleTransitionExpectedPointsModel(priors=priors, role_weights={99: 0.5})
        prior = model._player_prior({"code": 99})
        self.assertEqual(prior["games"], 10.0)
        self.assertEqual(prior["starts"], 8.0)
        self.assertEqual(prior["starter_minutes"], 640.0)
        self.assertEqual(prior["expected_goals"], 6.0)
        self.assertEqual(prior["expected_goals_minutes"], 1600.0)

    def test_transition_profiles_can_have_overlapping_tags(self) -> None:
        profile = TransitionProfile(
            player_code=7,
            target_team="Promoted FC",
            prior_team="Premier FC",
            same_club=False,
            club_change=True,
            new_to_fpl=False,
            promoted_team=True,
        )
        self.assertTrue(profile.transition)
        self.assertEqual(
            profile.labels(),
            ("all", "club_change", "promoted_team", "role_transition"),
        )

    def test_only_transition_players_receive_test_weight(self) -> None:
        profiles = {
            1: TransitionProfile(1, "A", "A", True, False, False, False),
            2: TransitionProfile(2, "B", "A", False, True, False, False),
            3: TransitionProfile(3, "C", None, False, False, True, True),
        }
        weights = transition_role_weights(profiles, transition_weight=0.25)
        self.assertNotIn(1, weights)
        self.assertEqual(weights[2], 0.25)
        self.assertEqual(weights[3], 0.25)


if __name__ == "__main__":
    unittest.main()
