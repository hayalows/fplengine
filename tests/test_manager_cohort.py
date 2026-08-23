import unittest

from fplengine.model import ExpectedPointsModel
from fplengine.service import analyze_manager_cohort

from .helpers import snapshot


class StubClient:
    def classic_league_standings(self, league_id: int, page: int = 1) -> dict:
        return {
            "league": {"id": league_id, "name": "Prior top cohort"},
            "standings": {
                "has_next": False,
                "results": [{"entry": 101}, {"entry": 102}],
            },
        }

    def entry_picks(self, entry_id: int, event_id: int) -> dict:
        captain = 1 if entry_id == 101 else 3
        return {
            "picks": [
                {"element": 1, "is_captain": captain == 1},
                {"element": 3, "is_captain": captain == 3},
            ]
        }


class ManagerCohortTests(unittest.TestCase):
    def test_consensus_uses_successful_sample_as_denominator(self) -> None:
        observed = snapshot()
        predictions = ExpectedPointsModel().predict(observed)
        report = analyze_manager_cohort(
            StubClient(), observed, predictions, sample_size=2, picks_event=2
        )
        self.assertEqual(report["metadata"]["successful_sample"], 2)
        self.assertEqual(report["selection_consensus"][0]["cohort_percent"], 100.0)
        self.assertEqual(len(report["captain_consensus"]), 2)


if __name__ == "__main__":
    unittest.main()
