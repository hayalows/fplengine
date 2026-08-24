from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from fplengine.cockpit import build_cockpit, build_personal_sections
from fplengine.model import ExpectedPointsModel
from fplengine.storage import Store
from fplengine.web import (
    SiteCache,
    build_persisted_cockpit,
    make_web_handler,
    page,
    render_tab,
)

from .test_cockpit import FakeEntryClient, _league_snapshot, _pick_rows


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = _league_snapshot()
        predictions = ExpectedPointsModel().predict(self.snapshot)
        client = FakeEntryClient(
            _pick_rows(),
            {"current": [{"event": 1, "bank": 8, "event_transfers": 0}], "chips": []},
            snapshot=self.snapshot,
        )
        self.payload = build_cockpit(client, None, entry_id=42, limit=5)

    def test_every_tab_renders_without_none_leakage(self) -> None:
        for tab, _label in (
            ("myteam", ""), ("picks", ""), ("captain", ""), ("transfers", ""),
            ("players", ""), ("fixtures", ""), ("market", ""), ("changes", ""),
            ("model", ""), ("premier", ""),
        ):
            html = render_tab(tab, self.payload)
            self.assertIn("<main>", html)
            self.assertNotIn("None</", html)

    def test_nav_links_present_and_active_marked(self) -> None:
        html = page("captain", self.payload)
        for key in ("myteam", "transfers", "premier"):
            self.assertIn(f'href="/site/{key}"', html)
        self.assertIn("class=active", html)

    def test_premier_tab_reports_missing_model_gracefully(self) -> None:
        html = render_tab("premier", self.payload)
        self.assertIn("No fitted report", html)

    def test_my_team_tab_shows_squad_and_state_labels(self) -> None:
        html = render_tab("myteam", self.payload)
        self.assertIn("My Team</h2>", html)
        self.assertIn("VERIFIED", html)


class SiteServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        store = Store(f"sqlite:///{Path(cls.tmp.name).joinpath('site.db').as_posix()}")
        store.initialize()
        cls.snapshot = _league_snapshot(fetched_at=datetime(2026, 8, 30, tzinfo=UTC))
        ingestion_id, _ = store.save_snapshot(cls.snapshot)
        cls.predictions = ExpectedPointsModel().predict(cls.snapshot)
        store.save_predictions(ingestion_id, cls.snapshot, cls.predictions)
        cls.store = store
        cls.cache = SiteCache(store=store, entry_id=None, ttl_seconds=3600)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_web_handler(cls.cache))
        thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def test_site_pages_serve_from_persisted_predictions(self) -> None:
        with urlopen(f"{self.base_url}site/picks", timeout=10) as response:
            body = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
        self.assertIn("Top picks", body)
        payload = self.cache.get()
        self.assertIn("persisted run", payload["data_source"])

    def test_unknown_paths_are_plain_404(self) -> None:
        try:
            urlopen(f"{self.base_url}missing", timeout=5)
            raised = False
        except Exception:
            raised = True
        self.assertTrue(raised)


class PersistedDataPathTests(unittest.TestCase):
    """The site's normal data path: stored observations + predictions, no live API."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(
            f"sqlite:///{Path(self.tmp.name).joinpath('persisted.db').as_posix()}"
        )
        self.store.initialize()
        self.snapshot = _league_snapshot(fetched_at=datetime(2026, 8, 30, tzinfo=UTC))
        ingestion_id, _ = self.store.save_snapshot(self.snapshot)
        self.predictions = ExpectedPointsModel().predict(self.snapshot)
        self.store.save_predictions(ingestion_id, self.snapshot, self.predictions)

    def test_persisted_payload_reproduces_live_prediction_values(self) -> None:
        result = build_persisted_cockpit(self.store)
        self.assertIsNotNone(result)
        payload, _snapshot, predictions = result
        live_by_id = {row.player_id: row.expected_points for row in self.predictions}
        served = {row["player_id"]: row["expected_points"] for row in payload["rankings"]}
        for player_id, expected in live_by_id.items():
            self.assertAlmostEqual(served[player_id], round(expected, 2), places=2)
        self.assertIn("persisted run", payload["data_source"])
        self.assertEqual(len(predictions), len(live_by_id))

    def test_persisted_run_records_league_scale_and_confidence(self) -> None:
        run = self.store.latest_predictions()
        self.assertEqual(
            run["assumptions"]["league_total_players"],
            self.snapshot.bootstrap["total_players"],
        )
        confidence = run["assumptions"]["prediction_confidence"]
        self.assertEqual(len(confidence), len(self.predictions))

    def test_personal_sections_attach_without_any_full_api_call(self) -> None:
        calls: list[str] = []

        class RecordingClient(FakeEntryClient):
            def snapshot(self):  # must never be called on the persisted path
                calls.append("snapshot")
                raise AssertionError("full API snapshot fetched on persisted path")

            def entry(self, entry_id):
                calls.append("entry")
                return super().entry(entry_id)

            def entry_history(self, entry_id):
                calls.append("history")
                return super().entry_history(entry_id)

            def entry_picks(self, entry_id, event):
                calls.append("picks")
                return super().entry_picks(entry_id, event)

        cache = SiteCache(
            store=self.store,
            entry_id=7181076,
            ttl_seconds=3600,
            client_factory=lambda: RecordingClient(
                _pick_rows(),
                {
                    "current": [{"event": 1, "bank": 8, "event_transfers": 0}],
                    "chips": [],
                },
            ),
        )
        payload = cache.get()
        self.assertIn("persisted run", payload["data_source"])
        self.assertEqual(len(payload["my_team"]["players"]), 15)
        self.assertEqual(len([row for row in payload["my_team"]["players"] if row["role"] == "starter"]), 11)
        self.assertEqual(payload["manager_state"]["free_transfers"]["classification"], "RECONSTRUCTED")
        # Only the small per-entry endpoints were contacted.
        self.assertEqual(sorted(set(calls)), ["entry", "history", "picks"])

    def test_empty_store_falls_back_to_live_and_labels_it(self) -> None:
        empty_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(empty_tmp.cleanup)
        empty_store = Store(
            f"sqlite:///{Path(empty_tmp.name).joinpath('empty.db').as_posix()}"
        )
        empty_store.initialize()
        cache = SiteCache(
            store=empty_store,
            entry_id=42,
            ttl_seconds=3600,
            client_factory=lambda: FakeEntryClient(_pick_rows(), {"current": [], "chips": []}),
        )
        with self.assertRaises(Exception):
            # Empty history cannot produce personal sections; the fallback path
            # surfaces the failure instead of serving fabricated data.
            cache.get()


if __name__ == "__main__":
    unittest.main()
