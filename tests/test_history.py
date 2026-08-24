import unittest

from fplengine.history import SeasonEvidence, merge_season_evidence


class HistoricalPriorTests(unittest.TestCase):
    def test_missing_xg_season_does_not_dilute_modern_xg_rate(self) -> None:
        old = SeasonEvidence(
            season="2021-22",
            players={
                "1": {
                    "position": "MID",
                    "team": "Alpha",
                    "minutes": 3000.0,
                    "games": 38.0,
                    "role_games": 0.0,
                    "starts": 0.0,
                    "starter_minutes": 0.0,
                    "substitute_appearances": 0.0,
                    "substitute_minutes": 0.0,
                    "expected_goals": 0.0,
                    "expected_assists": 0.0,
                    "saves": 0.0,
                    "defensive_contribution": 0.0,
                    "bonus": 20.0,
                    "yellow_cards": 3.0,
                    "red_cards": 0.0,
                    "total_points": 140.0,
                    "evidence_minutes": {"bonus": 3000.0, "yellow_cards": 3000.0, "red_cards": 3000.0},
                    "coverage": {"bonus": True, "yellow_cards": True, "red_cards": True},
                }
            },
            positions={},
            teams={},
            league={"fixtures": 0.0, "home_xg": 0.0, "away_xg": 0.0},
            coverage={"expected_goals": False},
            source_hashes={},
        )
        modern = SeasonEvidence(
            season="2022-23",
            players={
                "1": {
                    "position": "MID",
                    "team": "Alpha",
                    "minutes": 1800.0,
                    "games": 30.0,
                    "role_games": 30.0,
                    "starts": 20.0,
                    "starter_minutes": 1600.0,
                    "substitute_appearances": 5.0,
                    "substitute_minutes": 80.0,
                    "expected_goals": 6.0,
                    "expected_assists": 4.0,
                    "saves": 0.0,
                    "defensive_contribution": 0.0,
                    "bonus": 15.0,
                    "yellow_cards": 2.0,
                    "red_cards": 0.0,
                    "total_points": 120.0,
                    "evidence_minutes": {
                        "expected_goals": 1800.0,
                        "expected_assists": 1800.0,
                        "bonus": 1800.0,
                        "yellow_cards": 1800.0,
                        "red_cards": 1800.0,
                    },
                    "coverage": {
                        "starts": True,
                        "expected_goals": True,
                        "expected_assists": True,
                        "bonus": True,
                        "yellow_cards": True,
                        "red_cards": True,
                    },
                }
            },
            positions={},
            teams={},
            league={"fixtures": 380.0, "home_xg": 1.5, "away_xg": 1.2},
            coverage={"expected_goals": True},
            source_hashes={},
        )
        merged = merge_season_evidence([old, modern])
        player = merged["players"]["1"]
        self.assertEqual(player["evidence_minutes"]["expected_goals"], 1800.0)
        self.assertEqual(player["expected_goals"], 6.0)
        self.assertEqual(merged["history"]["depth"], 2)

    def test_recency_weighting_records_exact_season_weights(self) -> None:
        empty = lambda season: SeasonEvidence(
            season=season,
            players={},
            positions={},
            teams={},
            league={"fixtures": 0.0, "home_xg": 0.0, "away_xg": 0.0},
            coverage={},
            source_hashes={},
        )
        merged = merge_season_evidence(
            [empty("A"), empty("B"), empty("C")], half_life_seasons=1.0
        )
        self.assertEqual(merged["history"]["weights"], {"A": 0.25, "B": 0.5, "C": 1.0})


if __name__ == "__main__":
    unittest.main()
