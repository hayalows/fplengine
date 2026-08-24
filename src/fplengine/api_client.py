"""Small, resilient client for the public Fantasy Premier League endpoints.

The endpoints are public but not a formally documented public API. Keep this client
conservative: identify it, time out, retry transient failures, and never fan out calls
without an explicit command.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://fantasy.premierleague.com/api"
USER_AGENT = "fplengine/0.1 (+https://github.com/hayalows/fplengine)"


class FPLAPIError(RuntimeError):
    """Raised when an FPL endpoint cannot be read safely."""


@dataclass(frozen=True)
class Snapshot:
    bootstrap: dict[str, Any]
    fixtures: list[dict[str, Any]]
    fetched_at: datetime
    source_hash: str

    @classmethod
    def from_payloads(
        cls,
        bootstrap: dict[str, Any],
        fixtures: list[dict[str, Any]],
        fetched_at: datetime | None = None,
    ) -> Snapshot:
        observed_at = fetched_at or datetime.now(UTC)
        canonical = json.dumps(
            {"bootstrap": bootstrap, "fixtures": fixtures},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(bootstrap, fixtures, observed_at, hashlib.sha256(canonical).hexdigest())

    def event(self, event_id: int) -> dict[str, Any]:
        event = next((row for row in self.bootstrap["events"] if row["id"] == event_id), None)
        if event is None:
            raise ValueError(f"Unknown gameweek: {event_id}")
        return event

    def target_event(self, explicit_event: int | None = None) -> int:
        if explicit_event is not None:
            self.event(explicit_event)
            return explicit_event
        next_event = next((row for row in self.bootstrap["events"] if row.get("is_next")), None)
        if next_event:
            return int(next_event["id"])
        current = next((row for row in self.bootstrap["events"] if row.get("is_current")), None)
        if current:
            return int(current["id"])
        future = [row for row in self.bootstrap["events"] if not row.get("finished")]
        if future:
            return int(min(future, key=lambda row: row["id"])["id"])
        raise ValueError("No actionable gameweek is present in the FPL payload")


class FPLClient:
    def __init__(
        self,
        timeout_seconds: float = 30,
        max_retries: int = 3,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 1:
            raise ValueError("max_retries must be at least 1")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._opener = opener

    def _get(self, path: str) -> Any:
        url = f"{BASE_URL}/{path.lstrip('/')}"
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                with self._opener(request, timeout=self.timeout_seconds) as response:
                    payload = response.read()
                return json.loads(payload)
            except HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504}:
                    break
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
            if attempt + 1 < self.max_retries:
                time.sleep(2**attempt)
        raise FPLAPIError(f"GET {url} failed after {self.max_retries} attempt(s): {last_error}")

    def snapshot(self) -> Snapshot:
        bootstrap = self._get("bootstrap-static/")
        fixtures = self._get("fixtures/")
        if not isinstance(bootstrap, dict) or not isinstance(fixtures, list):
            raise FPLAPIError("FPL returned an unexpected bootstrap or fixtures payload")
        required = {"events", "elements", "teams", "element_types"}
        missing = required.difference(bootstrap)
        if missing:
            raise FPLAPIError(f"FPL bootstrap payload is missing: {sorted(missing)}")
        return Snapshot.from_payloads(bootstrap, fixtures)

    def bootstrap(self) -> dict[str, Any]:
        """Fetch only bootstrap-static; used by the lightweight market poll."""
        payload = self._get("bootstrap-static/")
        if not isinstance(payload, dict):
            raise FPLAPIError("FPL bootstrap-static response was not an object")
        return payload

    def element_summary(self, player_id: int) -> dict[str, Any]:
        return self._get(f"element-summary/{int(player_id)}/")

    def event_live(self, event_id: int) -> dict[str, Any]:
        return self._get(f"event/{int(event_id)}/live/")

    def entry(self, entry_id: int) -> dict[str, Any]:
        return self._get(f"entry/{int(entry_id)}/")

    def entry_history(self, entry_id: int) -> dict[str, Any]:
        return self._get(f"entry/{int(entry_id)}/history/")

    def entry_picks(self, entry_id: int, event_id: int) -> dict[str, Any]:
        return self._get(f"entry/{int(entry_id)}/event/{int(event_id)}/picks/")

    def entry_transfers(self, entry_id: int) -> list[dict[str, Any]]:
        payload = self._get(f"entry/{int(entry_id)}/transfers/")
        if not isinstance(payload, list):
            raise FPLAPIError(f"Entry {entry_id} transfers response was not a list")
        return payload

    def classic_league_standings(self, league_id: int, page: int = 1) -> dict[str, Any]:
        return self._get(
            f"leagues-classic/{int(league_id)}/standings/?page_standings={int(page)}"
        )
