"""Dependency-free read API for the v0.1 engine."""

from __future__ import annotations

import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .api_client import FPLClient
from .model import ExpectedPointsModel
from .service import analyze_manager, build_report, filter_rankings


class EngineCache:
    def __init__(self, ttl_seconds: int = 900) -> None:
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._loaded_at = 0.0
        self.snapshot = None
        self.predictions = None

    def get(self) -> tuple[Any, Any]:
        with self._lock:
            if self.snapshot is None or time.monotonic() - self._loaded_at >= self.ttl_seconds:
                self.snapshot = FPLClient().snapshot()
                self.predictions = ExpectedPointsModel().predict(self.snapshot)
                self._loaded_at = time.monotonic()
            return self.snapshot, self.predictions


def make_handler(cache: EngineCache) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "fplengine/0.1"

        def _json(self, status: HTTPStatus, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=60")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/health":
                    self._json(HTTPStatus.OK, {"status": "ok", "version": "0.1.0"})
                    return
                snapshot, predictions = cache.get()
                query = parse_qs(parsed.query)
                if parsed.path == "/rankings":
                    limit = min(100, max(1, int(query.get("limit", [20])[0])))
                    position = query.get("position", [None])[0]
                    rows = filter_rankings(predictions, position=position, limit=limit)
                    self._json(
                        HTTPStatus.OK,
                        {
                            "data_as_of": snapshot.fetched_at.isoformat(),
                            "target_event": predictions[0].target_event,
                            "model_version": predictions[0].model_version,
                            "results": [row.to_dict() for row in rows],
                        },
                    )
                    return
                if parsed.path == "/report":
                    limit = min(50, max(1, int(query.get("limit", [10])[0])))
                    self._json(HTTPStatus.OK, build_report(snapshot, predictions, limit))
                    return
                if parsed.path.startswith("/manager/"):
                    entry_id = int(parsed.path.rsplit("/", 1)[-1])
                    self._json(
                        HTTPStatus.OK,
                        analyze_manager(FPLClient(), snapshot, predictions, entry_id),
                    )
                    return
                self._json(
                    HTTPStatus.NOT_FOUND,
                    {"error": "not found", "routes": ["/health", "/rankings", "/report", "/manager/{id}"]},
                )
            except (ValueError, RuntimeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:  # boundary: convert unexpected failures to JSON
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": type(exc).__name__})

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8000, ttl_seconds: int = 900) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(EngineCache(ttl_seconds)))
    print(f"FPL Engine API listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
