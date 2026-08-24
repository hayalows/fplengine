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
from fplengine.web import SiteCache, make_web_handler, page, render_tab

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
        snapshot = _league_snapshot(fetched_at=datetime(2026, 8, 30, tzinfo=UTC))
        ingestion_id, _ = store.save_snapshot(snapshot)
        predictions = ExpectedPointsModel().predict(snapshot)
        store.save_predictions(ingestion_id, snapshot, predictions)
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


if __name__ == "__main__":
    unittest.main()
