CREATE SCHEMA IF NOT EXISTS engine;

CREATE TABLE IF NOT EXISTS engine.ingestion_run (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_hash char(64) NOT NULL UNIQUE CHECK (length(source_hash) = 64),
    source_name text NOT NULL,
    fetched_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('succeeded', 'failed')),
    player_count integer NOT NULL CHECK (player_count >= 0),
    team_count integer NOT NULL CHECK (team_count >= 0),
    fixture_count integer NOT NULL CHECK (fixture_count >= 0),
    observed_event integer,
    error text
);

CREATE TABLE IF NOT EXISTS engine.team (
    fpl_id integer PRIMARY KEY,
    code integer NOT NULL,
    name text NOT NULL,
    short_name text NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS engine.player (
    fpl_id integer PRIMARY KEY,
    fpl_code integer NOT NULL,
    opta_code text,
    first_name text NOT NULL,
    second_name text NOT NULL,
    web_name text NOT NULL,
    position_id smallint NOT NULL CHECK (position_id BETWEEN 1 AND 4),
    team_id integer NOT NULL REFERENCES engine.team(fpl_id),
    updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS player_code_idx ON engine.player(fpl_code);
CREATE INDEX IF NOT EXISTS player_opta_code_idx ON engine.player(opta_code) WHERE opta_code IS NOT NULL;

CREATE TABLE IF NOT EXISTS engine.fixture (
    fpl_id integer PRIMARY KEY,
    event_id smallint,
    kickoff_time timestamptz,
    home_team_id integer NOT NULL REFERENCES engine.team(fpl_id),
    away_team_id integer NOT NULL REFERENCES engine.team(fpl_id),
    home_score smallint,
    away_score smallint,
    started boolean NOT NULL,
    finished boolean NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS fixture_event_idx ON engine.fixture(event_id, kickoff_time);

CREATE TABLE IF NOT EXISTS engine.player_snapshot (
    ingestion_run_id bigint NOT NULL REFERENCES engine.ingestion_run(id),
    player_id integer NOT NULL REFERENCES engine.player(fpl_id),
    captured_at timestamptz NOT NULL,
    now_cost smallint NOT NULL,
    selected_percent numeric(6,3) NOT NULL,
    status text NOT NULL,
    chance_next smallint,
    news text NOT NULL,
    minutes integer NOT NULL,
    starts smallint NOT NULL,
    total_points integer NOT NULL,
    event_points smallint NOT NULL,
    transfers_in_event integer NOT NULL,
    transfers_out_event integer NOT NULL,
    expected_goals numeric(9,4) NOT NULL,
    expected_assists numeric(9,4) NOT NULL,
    expected_goals_conceded numeric(9,4) NOT NULL,
    defensive_contribution integer NOT NULL,
    PRIMARY KEY (ingestion_run_id, player_id)
);

CREATE INDEX IF NOT EXISTS player_snapshot_player_time_idx
ON engine.player_snapshot(player_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS engine.prediction_run (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingestion_run_id bigint NOT NULL REFERENCES engine.ingestion_run(id),
    source_hash char(64) NOT NULL,
    target_event smallint NOT NULL,
    model_version text NOT NULL,
    generated_at timestamptz NOT NULL,
    assumptions jsonb NOT NULL,
    UNIQUE (source_hash, target_event, model_version)
);

CREATE TABLE IF NOT EXISTS engine.player_prediction (
    prediction_run_id bigint NOT NULL REFERENCES engine.prediction_run(id),
    player_id integer NOT NULL REFERENCES engine.player(fpl_id),
    expected_minutes numeric(7,2) NOT NULL,
    expected_points numeric(8,3) NOT NULL,
    expected_goals numeric(8,3) NOT NULL,
    expected_assists numeric(8,3) NOT NULL,
    clean_sheet_probability numeric(7,5) NOT NULL,
    risk numeric(7,5) NOT NULL,
    lower_bound numeric(8,2) NOT NULL,
    upper_bound numeric(8,2) NOT NULL,
    components jsonb NOT NULL,
    actual_points smallint,
    absolute_error numeric(8,3),
    squared_error numeric(10,3),
    evaluated_at timestamptz,
    PRIMARY KEY (prediction_run_id, player_id)
);

CREATE INDEX IF NOT EXISTS prediction_event_idx
ON engine.prediction_run(target_event, generated_at DESC);

CREATE TABLE IF NOT EXISTS engine.manager_snapshot (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entry_id bigint NOT NULL,
    event_id smallint NOT NULL,
    captured_at timestamptz NOT NULL,
    overall_rank bigint,
    total_points integer,
    team_value integer,
    bank integer,
    payload jsonb NOT NULL,
    UNIQUE (entry_id, event_id, captured_at)
);

CREATE TABLE IF NOT EXISTS engine.manager_pick (
    manager_snapshot_id bigint NOT NULL REFERENCES engine.manager_snapshot(id),
    player_id integer NOT NULL REFERENCES engine.player(fpl_id),
    position smallint NOT NULL,
    multiplier smallint NOT NULL,
    is_captain boolean NOT NULL,
    is_vice_captain boolean NOT NULL,
    PRIMARY KEY (manager_snapshot_id, player_id)
);

COMMENT ON SCHEMA engine IS 'FPL Engine normalized observations and versioned predictions';
COMMENT ON COLUMN engine.player_snapshot.captured_at IS 'As-of timestamp used to prevent future-data leakage';
COMMENT ON COLUMN engine.player_prediction.components IS 'Calculated component breakdown, never raw observed data';
