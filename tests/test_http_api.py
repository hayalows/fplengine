import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

from fplengine.http_api import make_handler
from fplengine.model import ExpectedPointsModel

from .helpers import snapshot


class FixedCache:
    def __init__(self) -> None:
        self.snapshot = snapshot()
        self.predictions = ExpectedPointsModel().predict(self.snapshot)

    def get(self):
        return self.snapshot, self.predictions


class HTTPAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FixedCache()))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def get_json(self, path: str) -> tuple[int, dict]:
        try:
            with urlopen(f"{self.base_url}{path}", timeout=2) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            try:
                return exc.code, json.load(exc)
            finally:
                exc.close()

    def test_health_is_dependency_free(self) -> None:
        status, payload = self.get_json("/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ok", "version": "0.2.0"})

    def test_rankings_returns_bounded_versioned_results(self) -> None:
        status, payload = self.get_json("/rankings?limit=2&position=MID")
        self.assertEqual(status, 200)
        self.assertEqual(payload["target_event"], 3)
        self.assertEqual(payload["model_version"], "xp-v0.2.0")
        self.assertEqual(len(payload["results"]), 2)
        self.assertTrue(all(row["position"] == "MID" for row in payload["results"]))

    def test_unknown_route_is_json_404(self) -> None:
        status, payload = self.get_json("/missing")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "not found")

    def test_cockpit_route_returns_sections_without_store(self) -> None:
        status, payload = self.get_json("/cockpit?limit=3&player=Player%203")
        self.assertEqual(status, 200)
        self.assertEqual(payload["metadata"]["cockpit_version"], "cockpit-v0.1.0")
        self.assertIn("fixtures", payload)
        self.assertIn("rankings", payload)
        self.assertFalse(payload["changes_since_previous_snapshot"]["available"])
        # The shared five-player test snapshot cannot field a legal squad, so the
        # optimizer section must degrade independently instead of failing the brief.
        self.assertIn("error", payload["benchmark_squad"])
        self.assertIn("skipped", payload["your_transfers"])
        self.assertEqual(payload["player_detail"]["player_id"], 3)

    def test_player_route_returns_detail(self) -> None:
        status, payload = self.get_json("/player/1")
        self.assertEqual(status, 200)
        self.assertEqual(payload["player_id"], 1)
        self.assertIn("why_top_components", payload)


if __name__ == "__main__":
    unittest.main()
