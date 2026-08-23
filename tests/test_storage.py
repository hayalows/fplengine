import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fplengine.model import ExpectedPointsModel
from fplengine.storage import Store

from .helpers import snapshot


class StorageTests(unittest.TestCase):
    def test_schema_name_rejects_sql_fragments(self) -> None:
        with patch.dict("os.environ", {"FPLENGINE_DB_SCHEMA": "engine; DROP SCHEMA public"}):
            with self.assertRaisesRegex(ValueError, "simple SQL identifier"):
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


if __name__ == "__main__":
    unittest.main()
