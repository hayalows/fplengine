from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fplengine.historical import _fieldnames, _read_csv, history_window_variants, merge_season_evidence
from fplengine.historical_model import HistoricalExpectedPointsModel


class HistoricalEvidenceTests(unittest.TestCase):
    def test_latin1_archive_csv_preserves_accented_names_and_headers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gw1.csv"
            path.write_bytes(
                "name,element,position,minutes,total_points\nJosé Ángel,7,MID,90,6\n".encode(
                    "latin-1"
                )
            )
            rows = _read_csv(path)
            self.assertEqual(rows[0]["name"], "José Ángel")
            self.assertEqual(rows[0]["element"], "7")
            self.assertEqual(
                _fieldnames(path),
                {"name", "element", "position", "minutes", "total_points"},
            )

    def test_missing_old_xg_does_not_become_zero_evidence(self) -> None:
        old = {
            "schema_version": 2,
            "season": "2018-19",
            "field_availability": {"expected_goals": False, "starts": False},
            "players": {
                "42": {
                    "position": "FWD",
                    "team": "Old Club",
                    "games": 30.0,
                    "minutes": 2400.0,
                    "total_points": 120.0,
                    "opportunities": 30.0,
                }
            },
        }
        recent = {
            "schema_version": 2,
            "season": "2025-26",
            "field_availability": {"expected_goals": True, "starts": True},
            "players": {
                "42": {
                    "position": "FWD",
                    "team": "New Club",
                    "games": 20.0,
                    "minutes": 900.0,
                    "total_points": 80.0,
                    "opportunities": 20.0,
                    "starts": 10.0,
                    "starts_opportunities": 20.0,
                    "starter_minutes": 800.0,
                    "substitute_appearances": 5.0,
                    "substitute_minutes": 70.0,
                    "expected_goals": 6.0,
                    "expected_goals_minutes": 900.0,
                }
            },
        }
        merged = merge_season_evidence([old, recent], decay=1.0)
        player = merged["players"]["42"]
        self.assertEqual(player["minutes"], 3300.0)
        self.assertEqual(player["expected_goals"], 6.0)
        self.assertEqual(player["expected_goals_minutes"], 900.0)
        self.assertEqual(merged["field_seasons"]["expected_goals"], ["2025-26"])
        self.assertEqual(player["team"], "New Club")

    def test_recency_decay_weights_older_season(self) -> None:
        newer = {
            "schema_version": 2,
            "season": "2025-26",
            "field_availability": {"expected_goals": True},
            "players": {
                "7": {
                    "position": "MID",
                    "team": "A",
                    "games": 10.0,
                    "minutes": 900.0,
                    "total_points": 50.0,
                    "opportunities": 10.0,
                    "expected_goals": 4.0,
                    "expected_goals_minutes": 900.0,
                }
            },
        }
        older = {
            "schema_version": 2,
            "season": "2024-25",
            "field_availability": {"expected_goals": True},
            "players": {
                "7": {
                    "position": "MID",
                    "team": "A",
                    "games": 10.0,
                    "minutes": 900.0,
                    "total_points": 40.0,
                    "opportunities": 10.0,
                    "expected_goals": 2.0,
                    "expected_goals_minutes": 900.0,
                }
            },
        }
        merged = merge_season_evidence([older, newer], decay=0.5)
        player = merged["players"]["7"]
        self.assertEqual(player["expected_goals"], 5.0)
        self.assertEqual(player["expected_goals_minutes"], 1350.0)
        self.assertEqual(player["minutes"], 1350.0)

    def test_history_variants_are_explicit_and_reproducible(self) -> None:
        payloads = [
            {"schema_version": 2, "season": f"{year}-{str(year + 1)[-2:]}", "players": {}}
            for year in range(2016, 2026)
        ]
        variants = history_window_variants(payloads, windows=(1, 3, 10), decays=(1.0, 0.8))
        self.assertEqual(len(variants), 6)
        self.assertEqual(len(variants["history_1y_decay_1.00"]["source_seasons"]), 1)
        self.assertEqual(len(variants["history_3y_decay_0.80"]["source_seasons"]), 3)
        self.assertEqual(len(variants["history_10y_decay_1.00"]["source_seasons"]), 10)

    def test_historical_model_uses_field_specific_minutes(self) -> None:
        priors = {
            "positions": {"FWD": {"xg90": 0.36}},
            "players": {
                "99": {
                    "position": "FWD",
                    "team": "Club",
                    "minutes": 5000.0,
                    "expected_goals": 10.0,
                    "expected_goals_minutes": 1000.0,
                }
            },
            "source_seasons": ["2025-26", "2024-25"],
            "decay": 1.0,
        }
        model = HistoricalExpectedPointsModel(priors=priors)
        player = {
            "code": 99,
            "element_type": 4,
            "minutes": 0,
            "expected_goals": 0,
        }
        rate = model._posterior_rate(
            player,
            "expected_goals",
            "expected_goals",
            "xg90",
            0.36,
        )
        # If all 5,000 historical minutes were incorrectly used, this would be far lower.
        self.assertGreater(rate, 0.55)


if __name__ == "__main__":
    unittest.main()
