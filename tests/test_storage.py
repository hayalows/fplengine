import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fplengine.model import ExpectedPointsModel
from fplengine.storage import Store

from .helpers import snapshot


class StorageTests(unittest.TestCase):
    def test_schema_name_rejects_sql_fragments(self) -> None:
        with (
            patch.dict("os.environ", {"FPLENGINE_DB_SCHEMA": "engine; DROP SCHEMA public"}),
            self.assertRaisesRegex(ValueError, "simple SQL identifier"),
        ):
            Store("postgresql://example.invalid/database")

    def test_snapshot_and_prediction_runs_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Store(f"sqlite:///{Path(directory, 'engine.db').as_posix()}")
            store.initialize()
            observed = snapshot()
            first_id, first_inserted = store.save_snapshot(observed)
            second_id, second_inserted = store.save_snapshot(observed)
            self.assertTrue(first_inserted)
            self.assertFalse(second_inserted)
            self.assertEqual(first_id, second_id)
            predictions = ExpectedPointsModel().predict(observed)
            first_run = store.save_predictions(first_id, observed, predictions)
            second_run = store.save_predictions(first_id, observed, predictions)
            self.assertEqual(first_run, second_run)

    def test_evaluation_does_not_mutate_prediction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Store(f"sqlite:///{Path(directory, 'engine.db').as_posix()}")
            store.initialize()
            observed = snapshot()
            ingestion_id, _ = store.save_snapshot(observed)
            predictions = ExpectedPointsModel().predict(observed)
            run_id = store.save_predictions(ingestion_id, observed, predictions)
            result = store.evaluate(
                predictions[0].target_event,
                {row.player_id: 2 for row in predictions},
                "2099-01-01T00:00:00+00:00",
            )
            self.assertEqual(result["prediction_run_id"], run_id)
            with store.connect() as connection:
                forecast = connection.execute(
                    "SELECT actual_points FROM player_prediction WHERE prediction_run_id=? LIMIT 1",
                    (run_id,),
                ).fetchone()
                evaluation = connection.execute(
                    "SELECT COUNT(*) FROM player_prediction_evaluation WHERE prediction_run_id=?",
                    (run_id,),
                ).fetchone()
            self.assertIsNone(forecast["actual_points"])
            self.assertEqual(evaluation[0], len(predictions))


if __name__ == "__main__":
    unittest.main()
