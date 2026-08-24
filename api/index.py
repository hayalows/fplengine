"""Vercel serverless adapter for the persisted FPL Engine website.

This module contains no model logic. It reuses the existing Store, SiteCache and
HTML renderer from ``src/fplengine`` and expects the production Neon connection
string in ``FPLENGINE_DATABASE_URL``.
"""

from __future__ import annotations

import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fplengine.storage import Store  # noqa: E402
from fplengine.web import SiteCache, TABS, page  # noqa: E402

_DATABASE_URL = os.environ.get("FPLENGINE_DATABASE_URL")
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
        candidate = parsed.path.removeprefix("/site/").split("/", 1)[0]
        if candidate in _VALID_TABS:
            return candidate
    return "myteam"


class handler(BaseHTTPRequestHandler):
    """Single Vercel Function serving all website tabs through rewrites."""

    server_version = "fplengine-vercel/0.1"

    def do_GET(self) -> None:
        if _CACHE is None:
            body = (
                "FPL Engine is deployed but FPLENGINE_DATABASE_URL is not configured."
            ).encode("utf-8")
            self.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        try:
            payload = _CACHE.get()
            body = page(_requested_tab(self.path), payload).encode("utf-8")
        except Exception as exc:  # keep deployment failures observable, not silent
            body = f"FPL Engine request failed: {type(exc).__name__}: {exc}".encode("utf-8")
            self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "private, max-age=60")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return
