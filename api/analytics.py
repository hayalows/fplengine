"""First-party portfolio analytics collector and private reporting API.

Uses the existing Neon connection credentials but switches to the isolated
`pkm_analytics` database. No raw IP address is stored.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row

_ALLOWED_ORIGINS = {"https://pkm.hayalows.com"}
_ALLOWED_EVENTS = {
    "pageview",
    "session_start",
    "section_view",
    "click",
    "outbound",
    "engagement",
}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
_BOT_RE = re.compile(r"(bot|spider|crawler|crawl|slurp|headless|lighthouse)", re.I)
_RANGE_SQL = {
    "1d": "1 day",
    "7d": "7 days",
    "30d": "30 days",
    "90d": "90 days",
    "all": None,
}


def analytics_database_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    return urlunsplit((parts.scheme, parts.netloc, "/pkm_analytics", parts.query, parts.fragment))


def _text(value: Any, limit: int = 200) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value[:limit] if value else None


def _int(value: Any, minimum: int = 0, maximum: int = 100000) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(maximum, number))


def _origin(handler: Any) -> str:
    return (handler.headers.get("Origin") or "").rstrip("/")


def _set_cors(handler: Any) -> None:
    origin = _origin(handler)
    if origin in _ALLOWED_ORIGINS:
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")


def send_json(handler: Any, status: int, payload: Any) -> None:
    body = json.dumps(payload, separators=(",", ":"), default=_json_default).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Robots-Tag", "noindex")
    _set_cors(handler)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def send_empty(handler: Any, status: int = 204) -> None:
    handler.send_response(status)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Robots-Tag", "noindex")
    _set_cors(handler)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def handle_options(handler: Any) -> bool:
    if _origin(handler) not in _ALLOWED_ORIGINS:
        send_empty(handler, 403)
        return True
    handler.send_response(204)
    _set_cors(handler)
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
    handler.send_header("Access-Control-Max-Age", "86400")
    handler.send_header("Content-Length", "0")
    handler.end_headers()
    return True


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def _is_allowed_request(handler: Any) -> bool:
    origin = _origin(handler)
    return origin in _ALLOWED_ORIGINS


def collect(handler: Any, base_database_url: str) -> bool:
    if not _is_allowed_request(handler):
        send_json(handler, 403, {"error": "origin_not_allowed"})
        return True

    user_agent = handler.headers.get("User-Agent", "")
    if _BOT_RE.search(user_agent):
        send_empty(handler, 204)
        return True

    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        length = 0
    if length <= 0 or length > 16_384:
        send_json(handler, 400, {"error": "invalid_payload"})
        return True

    try:
        payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        send_json(handler, 400, {"error": "invalid_json"})
        return True

    event_name = _text(payload.get("event"), 40)
    visitor_id = _text(payload.get("visitorId"), 80)
    session_id = _text(payload.get("sessionId"), 80)
    if (
        event_name not in _ALLOWED_EVENTS
        or not visitor_id
        or not session_id
        or not _ID_RE.match(visitor_id)
        or not _ID_RE.match(session_id)
    ):
        send_json(handler, 400, {"error": "invalid_event"})
        return True

    path = _text(payload.get("path"), 300) or "/"
    if not path.startswith("/"):
        path = "/"

    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    event_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}

    country = _text(handler.headers.get("x-vercel-ip-country"), 8)
    region = _text(handler.headers.get("x-vercel-ip-country-region"), 32)

    session_values = (
        session_id,
        visitor_id,
        path,
        _text(context.get("referrerHost"), 180),
        country,
        region,
        _text(context.get("deviceType"), 32),
        _text(context.get("browser"), 64),
        _text(context.get("os"), 64),
        _text(context.get("language"), 32),
        _text(context.get("utmSource"), 120),
        _text(context.get("utmMedium"), 120),
        _text(context.get("utmCampaign"), 180),
        _int(context.get("viewportWidth"), 0, 10000),
        _int(context.get("screenWidth"), 0, 10000),
    )

    metadata = event_data.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    safe_metadata = {
        str(key)[:80]: value
        for key, value in list(metadata.items())[:12]
        if isinstance(value, (str, int, float, bool)) or value is None
    }

    db_url = analytics_database_url(base_database_url)
    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into analytics.sessions (
                      session_id, visitor_id, entry_path, referrer_host,
                      country_code, region_code, device_type, browser_name,
                      os_name, language, utm_source, utm_medium, utm_campaign,
                      viewport_width, screen_width
                    ) values (
                      %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                    )
                    on conflict (session_id) do update set
                      last_seen_at = now(),
                      country_code = coalesce(analytics.sessions.country_code, excluded.country_code),
                      region_code = coalesce(analytics.sessions.region_code, excluded.region_code),
                      device_type = coalesce(analytics.sessions.device_type, excluded.device_type),
                      browser_name = coalesce(analytics.sessions.browser_name, excluded.browser_name),
                      os_name = coalesce(analytics.sessions.os_name, excluded.os_name),
                      viewport_width = coalesce(excluded.viewport_width, analytics.sessions.viewport_width),
                      screen_width = coalesce(excluded.screen_width, analytics.sessions.screen_width)
                    """,
                    session_values,
                )
                cur.execute(
                    """
                    insert into analytics.events (
                      session_id, visitor_id, event_name, path, section_id,
                      target_type, target_label, target_url, duration_ms, metadata
                    ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                    """,
                    (
                        session_id,
                        visitor_id,
                        event_name,
                        path,
                        _text(event_data.get("sectionId"), 100),
                        _text(event_data.get("targetType"), 60),
                        _text(event_data.get("targetLabel"), 180),
                        _text(event_data.get("targetUrl"), 500),
                        _int(event_data.get("durationMs"), 0, 86_400_000),
                        json.dumps(safe_metadata, separators=(",", ":")),
                    ),
                )
        send_empty(handler, 204)
    except Exception as exc:
        print(f"Analytics collect failed: {type(exc).__name__}: {exc}")
        send_json(handler, 503, {"error": "analytics_unavailable"})
    return True


def _authorized(cur: Any, handler: Any) -> bool:
    auth = handler.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    token = auth[7:].strip()
    if len(token) < 20 or len(token) > 200:
        return False
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    cur.execute(
        "select value from analytics.settings where key='dashboard_token_sha256'"
    )
    row = cur.fetchone()
    if not row:
        return False
    stored = row.get("value") if isinstance(row, dict) else row[0]
    return hmac.compare_digest(str(stored), digest)


def _range_clause(range_name: str, column: str) -> tuple[str, tuple[Any, ...]]:
    interval = _RANGE_SQL.get(range_name, _RANGE_SQL["7d"])
    if interval is None:
        return "true", ()
    return f"{column} >= now() - %s::interval", (interval,)


def report(handler: Any, base_database_url: str, query: dict[str, list[str]]) -> bool:
    if not _is_allowed_request(handler):
        send_json(handler, 403, {"error": "origin_not_allowed"})
        return True

    range_name = (query.get("range") or ["7d"])[0]
    if range_name not in _RANGE_SQL:
        range_name = "7d"

    db_url = analytics_database_url(base_database_url)
    try:
        with psycopg.connect(db_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                if not _authorized(cur, handler):
                    send_json(handler, 401, {"error": "unauthorized"})
                    return True

                session_where, session_params = _range_clause(range_name, "started_at")
                event_where, event_params = _range_clause(range_name, "occurred_at")

                cur.execute(
                    f"""
                    select
                      count(*)::int as sessions,
                      count(distinct visitor_id)::int as visitors,
                      coalesce(round(avg(extract(epoch from (last_seen_at-started_at)))::numeric,1),0)::float8 as avg_session_seconds
                    from analytics.sessions
                    where {session_where}
                    """,
                    session_params,
                )
                metrics = cur.fetchone()

                cur.execute(
                    f"""
                    select count(*)::int as pageviews
                    from analytics.events
                    where event_name='pageview' and {event_where}
                    """,
                    event_params,
                )
                metrics["pageviews"] = cur.fetchone()["pageviews"]

                cur.execute(
                    """
                    select count(*)::int as active_now
                    from analytics.sessions
                    where last_seen_at >= now() - interval '5 minutes'
                    """
                )
                metrics["active_now"] = cur.fetchone()["active_now"]

                cur.execute(
                    f"""
                    with range_visitors as (
                      select distinct visitor_id
                      from analytics.sessions
                      where {session_where}
                    ),
                    lifetime as (
                      select s.visitor_id, count(*)::int as session_count
                      from analytics.sessions s
                      join range_visitors r using (visitor_id)
                      group by s.visitor_id
                    )
                    select
                      count(*) filter (where session_count = 1)::int as new_visitors,
                      count(*) filter (where session_count > 1)::int as returning_visitors
                    from lifetime
                    """,
                    session_params,
                )
                metrics.update(cur.fetchone())

                bucket = "hour" if range_name == "1d" else "day"
                cur.execute(
                    f"""
                    select date_trunc('{bucket}', occurred_at) as bucket,
                           count(*) filter (where event_name='pageview')::int as pageviews,
                           count(distinct visitor_id)::int as visitors
                    from analytics.events
                    where {event_where}
                    group by 1 order by 1
                    """,
                    event_params,
                )
                timeseries = cur.fetchall()

                def grouped(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
                    cur.execute(sql, params)
                    return list(cur.fetchall())

                top_paths = grouped(
                    f"""
                    select coalesce(path,'/') as label,
                           count(*)::int as value,
                           count(distinct visitor_id)::int as visitors
                    from analytics.events
                    where event_name='pageview' and {event_where}
                    group by 1 order by value desc limit 10
                    """,
                    event_params,
                )
                referrers = grouped(
                    f"""
                    select coalesce(nullif(referrer_host,''),'Direct') as label,
                           count(*)::int as value
                    from analytics.sessions
                    where {session_where}
                    group by 1 order by value desc limit 10
                    """,
                    session_params,
                )
                countries = grouped(
                    f"""
                    select coalesce(nullif(country_code,''),'Unknown') as label,
                           count(*)::int as value
                    from analytics.sessions
                    where {session_where}
                    group by 1 order by value desc limit 10
                    """,
                    session_params,
                )
                devices = grouped(
                    f"""
                    select coalesce(nullif(device_type,''),'Unknown') as label,
                           count(*)::int as value
                    from analytics.sessions
                    where {session_where}
                    group by 1 order by value desc limit 10
                    """,
                    session_params,
                )
                browsers = grouped(
                    f"""
                    select coalesce(nullif(browser_name,''),'Unknown') as label,
                           count(*)::int as value
                    from analytics.sessions
                    where {session_where}
                    group by 1 order by value desc limit 10
                    """,
                    session_params,
                )
                sections = grouped(
                    f"""
                    select coalesce(nullif(section_id,''),'Unknown') as label,
                           count(*)::int as value
                    from analytics.events
                    where event_name='section_view' and {event_where}
                    group by 1 order by value desc limit 12
                    """,
                    event_params,
                )
                interactions = grouped(
                    f"""
                    select coalesce(nullif(target_label,''), nullif(target_type,''), event_name) as label,
                           count(*)::int as value,
                           max(target_url) as target_url
                    from analytics.events
                    where event_name in ('click','outbound') and {event_where}
                    group by 1 order by value desc limit 12
                    """,
                    event_params,
                )
                recent = grouped(
                    f"""
                    select
                      e.occurred_at,
                      e.event_name,
                      e.path,
                      e.section_id,
                      e.target_label,
                      s.country_code,
                      s.region_code,
                      s.device_type,
                      s.browser_name,
                      s.referrer_host,
                      left(e.visitor_id,8) as visitor
                    from analytics.events e
                    left join analytics.sessions s using (session_id)
                    where {event_where}
                      and e.event_name <> 'engagement'
                    order by e.occurred_at desc
                    limit 40
                    """,
                    event_params,
                )
                live = grouped(
                    """
                    select
                      left(visitor_id,8) as visitor,
                      last_seen_at,
                      entry_path,
                      country_code,
                      region_code,
                      device_type,
                      browser_name,
                      referrer_host,
                      greatest(0, extract(epoch from (last_seen_at-started_at)))::int as seconds
                    from analytics.sessions
                    where last_seen_at >= now() - interval '5 minutes'
                    order by last_seen_at desc
                    limit 25
                    """,
                    (),
                )

        send_json(
            handler,
            200,
            {
                "range": range_name,
                "generatedAt": datetime.now(timezone.utc),
                "metrics": metrics,
                "timeseries": timeseries,
                "topPaths": top_paths,
                "referrers": referrers,
                "countries": countries,
                "devices": devices,
                "browsers": browsers,
                "sections": sections,
                "interactions": interactions,
                "recent": recent,
                "live": live,
            },
        )
    except Exception as exc:
        print(f"Analytics report failed: {type(exc).__name__}: {exc}")
        send_json(handler, 503, {"error": "analytics_unavailable"})
    return True
