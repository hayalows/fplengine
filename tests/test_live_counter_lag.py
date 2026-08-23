import unittest

from fplengine.model import ExpectedPointsModel

from .helpers import snapshot


class LiveCounterLagTests(unittest.TestCase):
    def test_player_start_is_counted_when_team_played_lags(self) -> None:
        observed = snapshot()
        observed.bootstrap["teams"][0]["played"] = 0
        rows = ExpectedPointsModel().predict(observed)
        started = next(row for row in rows if row.player_id == 1)
        self.assertLess(started.expected_minutes, 90)
        self.assertGreater(started.risk, 0)


if __name__ == "__main__":
    unittest.main()
