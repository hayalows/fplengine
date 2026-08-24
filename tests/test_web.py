from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from fplengine.cockpit import build_cockpit
from fplengine.model import ExpectedPointsModel
from fplengine.storage import Store
from fplengine.web import TABS, SiteCache, build_persisted_cockpit, make_web_handler, page

from .test_cockpit import FakeEntryClient, _league_snapshot, _pick_rows

ROUTES = [key for key, _label in TABS]


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
        self.payload.setdefault("market", {"available": False})
        self.payload.setdefault("season", {})
        self.payload.setdefault("freshness", {})
        self.payload.setdefault("all_players", [])

    def test_every_route_renders_without_none_leakage(self) -> None:
        for route in ROUTES:
            html = page(route, self.payload)
            self.assertIn("<!doctype html>", html)
            self.assertNotIn("None</", html)
            self.assertIn("</html>", html)

    def test_mobile_bottom_nav_and_desktop_header_present(self) -> None:
        html = page("transfers", self.payload)
        self.assertIn('aria-label="Primary"', html)
        self.assertIn("/site/market", html)
        self.assertIn("moresheet", html)
        self.assertIn('aria-current="page"', html)

    def test_unknown_routes_fall_back_to_home(self) -> str:
        html = page("not-a-route", self.payload)
        self.assertIn("Gameweek status", html)
        return html


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

    def test_all_site_routes_serve_over_http(self) -> None:
        for route in ROUTES:
            with urlopen(f"{self.base_url}site/{route}", timeout=30) as response:
                self.assertEqual(response.status, 200)
                body = response.read().decode("utf-8")
            self.assertIn("</html>", body)

    def test_root_redirects_to_home(self) -> None:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        try:
            opener.open(self.base_url, timeout=10)
            raise AssertionError("expected redirect")
        except urllib.error.HTTPError as exc:
            self.assertIn(exc.status, (301, 302, 307))


class PersistedDataPathTests(unittest.TestCase):
    """The site's normal data path: stored observations + predictions, no live API."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name).joinpath("persisted.db")
        self.store = Store(f"sqlite:///{self.db_path.as_posix()}")
        self.store.initialize()
        self.snapshot = _league_snapshot(fetched_at=datetime(2026, 8, 30, tzinfo=UTC))
        ingestion_id, _ = self.store.save_snapshot(self.snapshot)
        self.predictions = ExpectedPointsModel().predict(self.snapshot)
        self.store.save_predictions(ingestion_id, self.snapshot, self.predictions)

    def _seed_market_history(self) -> None:
        from datetime import timedelta

        now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
        base_elements = [
            {
                "id": row["id"],
                "now_cost": int(row["now_cost"]),
                "selected_by_percent": row["selected_by_percent"],
                "transfers_in_event": 4000 + row["id"] * 3,
                "transfers_out_event": 1000,
                "status": "a",
                "chance_of_playing_next_round": None,
                "news": "",
            }
            for row in self.snapshot.bootstrap["elements"][:20]
        ]
        older = [
            dict(row, transfers_in_event=row["transfers_in_event"] - 300) for row in base_elements
        ]
        self.store.save_market_poll(
            older, (now - timedelta(hours=7)).isoformat(), "e" * 64, event_id=2
        )
        self.store.save_market_poll(
            base_elements,
            (now - timedelta(minutes=10)).isoformat(),
            "f" * 64,
            event_id=2,
        )

    def test_persisted_payload_includes_market_season_and_freshness(self) -> None:
        self._seed_market_history()
        result = build_persisted_cockpit(self.store)
        self.assertIsNotNone(result)
        payload, _snapshot, predictions = result
        self.assertTrue(payload["market"]["available"])
        rows = payload["market"]["players"]
        self.assertTrue(rows)
        first = rows[0]
        for field in ("name", "team", "position", "pressure_level", "net_transfers"):
            self.assertIn(field, first)
        self.assertTrue(any(row["net_transfers_6h"] not in (None, 0) for row in rows))
        self.assertEqual(predictions[0].model_version, "xp-v0.2.0")

    def test_deadline_metadata_flows_from_season_events(self) -> None:
        events = [
            {
                "id": 3,
                "name": "Gameweek 3",
                "deadline_time": "2026-09-01T10:00:00Z",
                "is_next": True,
                "is_current": False,
                "finished": False,
            }
        ]
        self.store.save_season_events(events, "2026-08-30T00:00:00+00:00")
        payload, _snapshot, _predictions = build_persisted_cockpit(self.store)
        self.assertEqual(payload["season"]["deadline_utc"], "2026-09-01T10:00:00Z")
        html = page("home", payload)
        self.assertIn('data-deadline="2026-09-01T10:00:00Z"', html)

    def test_personal_sections_attach_without_any_full_api_call(self) -> None:
        calls: list[str] = []

        class RecordingClient(FakeEntryClient):
            def snapshot(self):  # must never be called on the persisted path
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
        starters = [row for row in payload["my_team"]["players"] if row["role"] == "starter"]
        self.assertEqual(len(starters), 11)
        self.assertEqual(
            payload["manager_state"]["free_transfers"]["classification"],
            "RECONSTRUCTED",
        )
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
            cache.get()


if __name__ == "__main__":
    unittest.main()
