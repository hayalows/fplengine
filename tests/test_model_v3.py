import unittest

from fplengine.model_v3 import ExpectedPointsModelV3

from .helpers import snapshot


class ModelV3Tests(unittest.TestCase):
    def _priors(self, team: str = "Alpha") -> dict:
        return {
            "schema_version": 2,
            "league": {},
            "teams": {"Alpha": {}, "Beta": {}},
            "positions": {
                "MID": {
                    "start_rate": 0.7,
                    "starter_minutes": 80.0,
                    "cameo_rate": 0.25,
                    "cameo_minutes": 14.0,
                    "xg90": 0.2,
                    "xa90": 0.17,
                    "dc90": 6.5,
                    "bonus90": 0.35,
                    "yellow90": 0.1,
                    "red90": 0.008,
                },
                "DEF": {"start_rate": 0.7, "starter_minutes": 84.0, "cameo_rate": 0.1, "cameo_minutes": 10.0},
                "FWD": {"start_rate": 0.65, "starter_minutes": 78.0, "cameo_rate": 0.25, "cameo_minutes": 15.0},
                "GK": {"start_rate": 0.5, "starter_minutes": 90.0, "cameo_rate": 0.01, "cameo_minutes": 1.0},
            },
            "players": {
                "1001": {
                    "position": "MID",
                    "team": team,
                    "minutes": 2500.0,
                    "games": 34.0,
                    "role_games": 34.0,
                    "starts": 30.0,
                    "starter_minutes": 2400.0,
                    "substitute_appearances": 2.0,
                    "substitute_minutes": 30.0,
                    "expected_goals": 8.0,
                    "expected_assists": 7.0,
                    "defensive_contribution": 120.0,
                    "bonus": 20.0,
                    "yellow_cards": 4.0,
                    "red_cards": 0.0,
                    "saves": 0.0,
                    "evidence_minutes": {
                        "expected_goals": 2500.0,
                        "expected_assists": 2500.0,
                        "defensive_contribution": 2500.0,
                        "bonus": 2500.0,
                        "yellow_cards": 2500.0,
                        "red_cards": 2500.0,
                        "saves": 2500.0,
                    },
                }
            },
            "history": {"depth": 5},
        }

    def test_club_change_increases_risk_and_reduces_historical_role_retention(self) -> None:
        observed = snapshot()
        continuity = ExpectedPointsModelV3(priors=self._priors("Alpha"), transition_retention=0.5)
        moved = ExpectedPointsModelV3(priors=self._priors("Beta"), transition_retention=0.5)
        normal = next(row for row in continuity.predict(observed) if row.player_id == 1)
        changed = next(row for row in moved.predict(observed) if row.player_id == 1)
        self.assertEqual(changed.provenance["role_transition"], "club_change")
        self.assertGreater(changed.risk, normal.risk)
        self.assertGreater(changed.upper_bound - changed.lower_bound, normal.upper_bound - normal.lower_bound)

    def test_field_specific_minutes_prevent_missing_old_xg_from_becoming_zero(self) -> None:
        observed = snapshot()
        priors = self._priors("Alpha")
        priors["players"]["1001"]["minutes"] = 9000.0
        priors["players"]["1001"]["evidence_minutes"]["expected_goals"] = 2500.0
        model = ExpectedPointsModelV3(priors=priors)
        player = observed.bootstrap["elements"][0]
        rate = model._posterior_rate(player, "expected_goals", "expected_goals", "xg90", 0.2)
        self.assertGreater(rate, 0.20)


if __name__ == "__main__":
    unittest.main()
