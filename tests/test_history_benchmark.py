from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fplengine.history_benchmark import _average_metric_rows, run_history_depth_experiment


class HistoryBenchmarkTests(unittest.TestCase):
    def test_metric_rows_are_averaged_per_gameweek(self) -> None:
        result = _average_metric_rows(
            [
                {"mae": 1.0, "ndcg_at_10": 0.2},
                {"mae": 3.0, "ndcg_at_10": 0.6},
            ]
        )
        self.assertEqual(result["mae"], 2.0)
        self.assertEqual(result["ndcg_at_10"], 0.4)

    def test_future_season_cannot_enter_prior_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "must precede"):
                run_history_depth_experiment(
                    Path(directory),
                    target_season="2025-26",
                    prior_seasons=["2024-25", "2025-26"],
                )


if __name__ == "__main__":
    unittest.main()
