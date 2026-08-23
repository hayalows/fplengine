import unittest

from fplengine.model import ExpectedPointsModel

from .helpers import player, snapshot


class ExpectedPointsModelTests(unittest.TestCase):
    def test_zeroed_legacy_strength_fields_do_not_force_minimum_goal_rates(self) -> None:
        observed = snapshot()
        home, away = observed.bootstrap["teams"]
        for team in (home, away):
            for field in (
                "strength_attack_home",
                "strength_attack_away",
                "strength_defence_home",
                "strength_defence_away",
            ):
                team[field] = 0
        home["strength_overall_home"] = 5
        away["strength_overall_away"] = 2
        home_xg, away_xg = ExpectedPointsModel(priors={})._team_goal_rates(home, away)
        self.assertGreater(home_xg, 1.0)
        self.assertGreater(away_xg, 0.5)
        self.assertGreater(home_xg, away_xg)

    def test_ownership_does_not_determine_expected_minutes(self) -> None:
        low_owned = player(10, 1, 3, ownership="0.1")
        high_owned = dict(low_owned, id=11, code=1011, selected_by_percent="80.0")
        model = ExpectedPointsModel(priors={})
        low_projection = model._minutes_projection(low_owned, team_played=2)
        high_projection = model._minutes_projection(high_owned, team_played=2)
        self.assertAlmostEqual(
            low_projection.expected_minutes, high_projection.expected_minutes
        )

    def test_prior_starter_evidence_separates_identical_current_players(self) -> None:
        regular = player(10, 1, 3, starts=1, minutes=90)
        fringe = player(11, 1, 3, starts=1, minutes=90)
        priors = {
            "positions": {},
            "teams": {},
            "league": {},
            "players": {
                "1010": {"games": 38, "starts": 36, "starter_minutes": 2920},
                "1011": {"games": 38, "starts": 2, "starter_minutes": 120},
            },
        }
        model = ExpectedPointsModel(priors=priors)
        regular_projection = model._minutes_projection(regular, team_played=1)
        fringe_projection = model._minutes_projection(fringe, team_played=1)
        self.assertGreater(regular_projection.expected_minutes, fringe_projection.expected_minutes)
        self.assertGreater(
            regular_projection.start_probability, fringe_projection.start_probability
        )

    def test_minutes_probabilities_are_coherent(self) -> None:
        projection = ExpectedPointsModel(priors={})._minutes_projection(
            player(10, 1, 3), team_played=2
        )
        self.assertGreaterEqual(projection.appearance_probability, projection.sixty_probability)
        self.assertLessEqual(
            projection.expected_minutes, 90.0 * projection.appearance_probability
        )
        self.assertGreaterEqual(
            projection.expected_minutes, 60.0 * projection.sixty_probability
        )

    def test_predictions_are_finite_ranked_and_versioned(self) -> None:
        rows = ExpectedPointsModel().predict(snapshot())
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row.target_event == 3 for row in rows))
        self.assertTrue(all(row.model_version == "xp-v0.2.0" for row in rows))
        self.assertEqual(rows, sorted(rows, key=lambda row: row.expected_points, reverse=True))
        self.assertTrue(all(row.lower_bound <= row.expected_points <= row.upper_bound for row in rows))

    def test_injured_player_has_no_minutes_or_attacking_allocation(self) -> None:
        rows = ExpectedPointsModel().predict(snapshot())
        injured = next(row for row in rows if row.player_id == 5)
        self.assertEqual(injured.expected_minutes, 0)
        self.assertEqual(injured.expected_goals, 0)
        self.assertEqual(injured.expected_assists, 0)
        self.assertGreaterEqual(injured.risk, 0.99)

    def test_double_gameweek_accumulates_both_fixtures(self) -> None:
        single = {row.player_id: row for row in ExpectedPointsModel().predict(snapshot())}
        double = {row.player_id: row for row in ExpectedPointsModel().predict(snapshot(double=True))}
        self.assertEqual(double[1].fixture_count, 2)
        self.assertGreater(double[1].expected_points, single[1].expected_points)
        self.assertAlmostEqual(double[1].expected_minutes, 2 * single[1].expected_minutes, places=1)

    def test_blank_gameweek_is_zero_points(self) -> None:
        rows = ExpectedPointsModel().predict(snapshot(blank=True))
        self.assertTrue(all(row.fixture_count == 0 for row in rows))
        self.assertTrue(all(row.expected_points == 0 for row in rows))


if __name__ == "__main__":
    unittest.main()
