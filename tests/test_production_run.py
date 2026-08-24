import unittest
from unittest.mock import MagicMock, patch

from fplengine.production_run import run_once


class ProductionRunTests(unittest.TestCase):
    def test_run_once_never_initializes_schema(self) -> None:
        snapshot = MagicMock()
        snapshot.source_hash = "a" * 64
        snapshot.fetched_at.isoformat.return_value = "2026-08-24T00:00:00+00:00"
        snapshot.bootstrap = {"elements": [1, 2], "teams": [1]}
        snapshot.fixtures = [1, 2, 3]

        prediction = MagicMock()
        prediction.target_event = 2
        prediction.model_version = "xp-v0.2.0"

        with (
            patch("fplengine.production_run.FPLClient") as client_cls,
            patch("fplengine.production_run.ExpectedPointsModel") as model_cls,
            patch("fplengine.production_run.Store") as store_cls,
        ):
            client_cls.return_value.snapshot.return_value = snapshot
            model_cls.return_value.predict.return_value = [prediction]
            store = store_cls.return_value
            store.is_postgres = True
            store.save_snapshot.return_value = (7, True)
            store.save_predictions.return_value = 11

            result = run_once("postgresql://example.invalid/neondb")

            store.initialize.assert_not_called()
            store.save_snapshot.assert_called_once_with(snapshot)
            store.save_season_events.assert_called_once_with(
                [], "2026-08-24T00:00:00+00:00"
            )
            store.save_predictions.assert_called_once_with(7, snapshot, [prediction])
            self.assertEqual(result["ingestion_run_id"], 7)
            self.assertEqual(result["prediction_run_id"], 11)
            self.assertTrue(result["new_source_snapshot"])

    def test_run_once_rejects_non_postgres(self) -> None:
        with (
            patch("fplengine.production_run.FPLClient") as client_cls,
            patch("fplengine.production_run.ExpectedPointsModel") as model_cls,
            patch("fplengine.production_run.Store") as store_cls,
        ):
            client_cls.return_value.snapshot.return_value = MagicMock()
            model_cls.return_value.predict.return_value = [MagicMock()]
            store_cls.return_value.is_postgres = False
            with self.assertRaisesRegex(RuntimeError, "PostgreSQL production database"):
                run_once("sqlite:///local.db")


if __name__ == "__main__":
    unittest.main()
