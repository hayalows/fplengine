-- Migration 002: season event metadata and the lightweight market-intelligence store.
--
-- season_event persists official gameweek metadata (notably deadlines) during
-- ingestion so read paths can show countdowns without touching the FPL API.
--
-- market_poll / market_state are a compact sliding-window time series of official
-- market fields captured by a lightweight scheduled poll that never runs the model.
-- Retention (default 7 days) is enforced by the poll itself; at ~570 players and
-- 30-minute cadence this is roughly 190k small rows, i.e. low tens of megabytes.

CREATE TABLE IF NOT EXISTS engine.season_event (
    fpl_id integer PRIMARY KEY,
    name text NOT NULL,
    deadline_time timestamptz,
    is_next boolean NOT NULL DEFAULT false,
    is_current boolean NOT NULL DEFAULT false,
    finished boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS engine.market_poll (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_hash char(64) NOT NULL UNIQUE CHECK (length(source_hash) = 64),
    captured_at timestamptz NOT NULL,
    event_id smallint,
    player_count integer NOT NULL CHECK (player_count >= 0)
);

CREATE INDEX IF NOT EXISTS market_poll_captured_idx ON engine.market_poll(captured_at DESC);

CREATE TABLE IF NOT EXISTS engine.market_state (
    poll_id bigint NOT NULL REFERENCES engine.market_poll(id),
    player_id integer NOT NULL,
    now_cost smallint NOT NULL,
    selected_percent numeric(6,3) NOT NULL,
    transfers_in_event integer NOT NULL,
    transfers_out_event integer NOT NULL,
    status text NOT NULL,
    chance_next smallint,
    news text NOT NULL,
    PRIMARY KEY (poll_id, player_id)
);

-- Deliberately no foreign key on market_state.player_id: a newly added FPL player
-- must be capturable before the slower six-hourly identity ingestion runs.
CREATE INDEX IF NOT EXISTS market_state_player_idx ON engine.market_state(player_id, poll_id);

-- event_id notes which gameweek a poll's transfer counters belong to (counters
-- reset at every deadline), so derived deltas never cross gameweek boundaries.
