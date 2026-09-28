"""Vercel serverless adapter for FPL Engine and portfolio analytics."""

from __future__ import annotations

import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
API_DIR = Path(__file__).resolve().parent
for path in (SRC, API_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

if not os.environ.get("FPLENGINE_DB_SCHEMA", "").strip():
    os.environ["FPLENGINE_DB_SCHEMA"] = "engine"

try:
    from psycopg.types.json import set_json_loads

    def _raw_json(value: str | bytes) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else value

    set_json_loads(_raw_json)
except ImportError:
    pass

from analytics import (  # noqa: E402
    collect as analytics_collect,
    handle_options as analytics_options,
    report as analytics_report,
)
from fplengine.storage import Store  # noqa: E402
from fplengine.web import SiteCache, TABS, page  # noqa: E402

_DATABASE_URL = (
    os.environ.get("FPLENGINE_DATABASE_URL")
    or os.environ.get("NEON_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
)
_ENTRY_ID = int(os.environ.get("FPLENGINE_ENTRY_ID", "7181076"))
_TTL_SECONDS = int(os.environ.get("FPLENGINE_WEB_TTL", "900"))

_CACHE = (
    SiteCache(
        store=Store(_DATABASE_URL),
        entry_id=_ENTRY_ID,
        ttl_seconds=_TTL_SECONDS,
    )
    if _DATABASE_URL
    else None
)
_VALID_TABS = {key for key, _label in TABS}


def _requested_tab(path: str) -> str:
    parsed = urlparse(path)
    query = parse_qs(parsed.query)
    candidate = query.get("tab", [None])[0]
    if candidate in _VALID_TABS:
        return str(candidate)
    if parsed.path.startswith("/site/"):
        candidate = parsed.path.removeprefix("/site/").rstrip("/").split("/", 1)[0]
        if candidate in _VALID_TABS:
            return candidate
    return "home"


def _normalize_persisted_types(payload: dict[str, Any]) -> None:
    changes = payload.get("changes_since_previous_snapshot") or {}
    for key in ("previous_captured_at", "latest_captured_at"):
        value = changes.get(key)
        if value is not None and hasattr(value, "isoformat"):
            changes[key] = value.isoformat()


def _analytics_query(path: str) -> tuple[str | None, dict[str, list[str]]]:
    parsed = urlparse(path)
    query = parse_qs(parsed.query)
    return (query.get("analytics") or [None])[0], query


def _send_plain(handler: BaseHTTPRequestHandler, status: int, text: str) -> None:
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Robots-Tag", "noindex")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    """Single Vercel Function serving FPL pages and portfolio analytics."""

    server_version = "fplengine-vercel/0.2"

    def do_OPTIONS(self) -> None:
        analytics_mode, _query = _analytics_query(self.path)
        if analytics_mode in {"collect", "report"}:
            analytics_options(self)
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        analytics_mode, _query = _analytics_query(self.path)
        if analytics_mode != "collect":
            _send_plain(self, HTTPStatus.NOT_FOUND, "Not found.")
            return
        if not _DATABASE_URL:
            _send_plain(self, HTTPStatus.SERVICE_UNAVAILABLE, "Analytics database unavailable.")
            return
        analytics_collect(self, _DATABASE_URL)

    def do_GET(self) -> None:
        analytics_mode, query = _analytics_query(self.path)
        if analytics_mode == "report":
            if not _DATABASE_URL:
                _send_plain(self, HTTPStatus.SERVICE_UNAVAILABLE, "Analytics database unavailable.")
                return
            analytics_report(self, _DATABASE_URL, query)
            return
        if analytics_mode == "collect":
            _send_plain(self, HTTPStatus.METHOD_NOT_ALLOWED, "Use POST.")
            return

        if _CACHE is None:
            _send_plain(
                self,
                HTTPStatus.SERVICE_UNAVAILABLE,
                "FPL Engine is deployed but no Neon database URL is configured.",
            )
            return

        try:
            payload = _CACHE.get()
            _normalize_persisted_types(payload)
            body = page(_requested_tab(self.path), payload).encode("utf-8")
        except Exception as exc:
            print(f"FPL Engine request failed: {type(exc).__name__}: {exc}")
            _send_plain(
                self,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "FPL Engine request failed. Check deployment runtime logs.",
            )
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "private, max-age=60")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return
