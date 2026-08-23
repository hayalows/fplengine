import unittest

from fplengine.model import ExpectedPointsModel

from .helpers import snapshot


class ExpectedPointsModelTests(unittest.TestCase):
    def test_predictions_are_finite_ranked_and_versioned(self) -> None:
        rows = ExpectedPointsModel().predict(snapshot())
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(row.target_event == 3 for row in rows))
        self.assertTrue(all(row.model_version == "xp-v0.1.0" for row in rows))
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
