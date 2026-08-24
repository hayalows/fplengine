from __future__ import annotations

import unittest

from fplengine.component_history import component_history_prior, component_window_variants


def season_payload(season: str, *, starts: float, xg: float, bonus: float) -> dict:
    return {
        "schema_version": 2,
        "season": season,
        "field_availability": {
            "starts": True,
            "expected_goals": True,
            "bonus": True,
        },
        "players": {
            "10": {
                "position": "MID",
                "team": f"Club {season}",
                "games": 20.0,
                "minutes": 900.0,
                "total_points": 50.0,
                "opportunities": 20.0,
                "starts": starts,
                "starts_opportunities": 20.0,
                "starter_minutes": starts * 80.0,
                "substitute_appearances": 2.0,
                "substitute_minutes": 30.0,
                "expected_goals": xg,
                "expected_goals_minutes": 900.0,
                "bonus": bonus,
                "bonus_minutes": 900.0,
            }
        },
    }


class ComponentHistoryTests(unittest.TestCase):
    def test_each_component_uses_its_own_history_window(self) -> None:
        payloads = [
            season_payload("2022-23", starts=30.0, xg=12.0, bonus=15.0),
            season_payload("2023-24", starts=20.0, xg=6.0, bonus=10.0),
            season_payload("2024-25", starts=10.0, xg=2.0, bonus=5.0),
        ]
        prior = component_history_prior(
            payloads,
            role_window=1,
            attack_window=2,
            ancillary_window=3,
        )
        player = prior["players"]["10"]
        self.assertEqual(player["starts"], 10.0)
        self.assertEqual(player["starts_opportunities"], 20.0)
        self.assertEqual(player["expected_goals"], 8.0)
        self.assertEqual(player["expected_goals_minutes"], 1800.0)
        self.assertEqual(player["bonus"], 30.0)
        self.assertEqual(player["bonus_minutes"], 2700.0)
        self.assertEqual(player["team"], "Club 2024-25")
        self.assertEqual(
            prior["component_sources"]["role"]["seasons"],
            ["2024-25"],
        )
        self.assertEqual(
            prior["component_sources"]["attack"]["seasons"],
            ["2024-25", "2023-24"],
        )
        self.assertEqual(
            prior["component_sources"]["ancillary"]["seasons"],
            ["2024-25", "2023-24", "2022-23"],
        )

    def test_component_grid_is_explicit(self) -> None:
        payloads = [season_payload("2024-25", starts=10.0, xg=2.0, bonus=5.0)]
        variants = component_window_variants(
            payloads,
            role_windows=(1, 2),
            attack_windows=(1, 3),
            ancillary_windows=(1, 5),
        )
        self.assertEqual(len(variants), 8)
        self.assertIn("role2_attack3_ancillary5_decay1.00", variants)


if __name__ == "__main__":
    unittest.main()
