-- Migration 002: season event metadata and the lightweight market-intelligence store.
--
-- season_event persists official gameweek metadata (notably deadlines) during
-- ingestion so read paths can show countdowns without touching the FPL API.
--
-- market_poll / market_state are a compact sliding-window time series of official
-- market fields captured by a lightweight scheduled poll that never runs the model.
-- Retention (default 7 days) is enforced by the poll itself; at ~570 players and
-- 30-minute cadence this is roughly 190k small rows, i.e. low tens of megabytes.

CREATE TABLE IF NOT EXISTS season_event (
    fpl_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    deadline_time TEXT,
    is_next INTEGER NOT NULL DEFAULT 0,
    is_current INTEGER NOT NULL DEFAULT 0,
    finished INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_poll (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_hash CHAR(64) NOT NULL UNIQUE CHECK (length(source_hash) = 64),
    captured_at TEXT NOT NULL,
    event_id SMALLINT,
    player_count INTEGER NOT NULL CHECK (player_count >= 0)
);

CREATE INDEX IF NOT EXISTS market_poll_captured_idx ON market_poll(captured_at DESC);

CREATE TABLE IF NOT EXISTS market_state (
    poll_id INTEGER NOT NULL REFERENCES market_poll(id),
    player_id INTEGER NOT NULL,
    now_cost SMALLINT NOT NULL,
    selected_percent NUMERIC(6,3) NOT NULL,
    transfers_in_event INTEGER NOT NULL,
    transfers_out_event INTEGER NOT NULL,
    status TEXT NOT NULL,
    chance_next SMALLINT,
    news TEXT NOT NULL,
    PRIMARY KEY (poll_id, player_id)
);

-- Deliberately no foreign key on market_state.player_id: a newly added FPL player
-- must be capturable before the slower six-hourly identity ingestion runs.
CREATE INDEX IF NOT EXISTS market_state_player_idx ON market_state(player_id, poll_id);

-- event_id notes which gameweek a poll's transfer counters belong to (counters
-- reset at every deadline), so derived deltas never cross gameweek boundaries.
