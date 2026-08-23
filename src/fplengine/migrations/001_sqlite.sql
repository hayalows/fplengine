PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ingestion_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_hash TEXT NOT NULL UNIQUE CHECK (length(source_hash) = 64),
    source_name TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    status TEXT NOT NULL,
    player_count INTEGER NOT NULL,
    team_count INTEGER NOT NULL,
    fixture_count INTEGER NOT NULL,
    observed_event INTEGER,
    error TEXT
);

CREATE TABLE IF NOT EXISTS team (
    fpl_id INTEGER PRIMARY KEY,
    code INTEGER NOT NULL,
    name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS player (
    fpl_id INTEGER PRIMARY KEY,
    fpl_code INTEGER NOT NULL,
    opta_code TEXT,
    first_name TEXT NOT NULL,
    second_name TEXT NOT NULL,
    web_name TEXT NOT NULL,
    position_id INTEGER NOT NULL,
    team_id INTEGER NOT NULL REFERENCES team(fpl_id),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fixture (
    fpl_id INTEGER PRIMARY KEY,
    event_id INTEGER,
    kickoff_time TEXT,
    home_team_id INTEGER NOT NULL REFERENCES team(fpl_id),
    away_team_id INTEGER NOT NULL REFERENCES team(fpl_id),
    home_score INTEGER,
    away_score INTEGER,
    started INTEGER NOT NULL,
    finished INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS player_snapshot (
    ingestion_run_id INTEGER NOT NULL REFERENCES ingestion_run(id),
    player_id INTEGER NOT NULL REFERENCES player(fpl_id),
    captured_at TEXT NOT NULL,
    now_cost INTEGER NOT NULL,
    selected_percent REAL NOT NULL,
    status TEXT NOT NULL,
    chance_next INTEGER,
    news TEXT NOT NULL,
    minutes INTEGER NOT NULL,
    starts INTEGER NOT NULL,
    total_points INTEGER NOT NULL,
    event_points INTEGER NOT NULL,
    transfers_in_event INTEGER NOT NULL,
    transfers_out_event INTEGER NOT NULL,
    expected_goals REAL NOT NULL,
    expected_assists REAL NOT NULL,
    expected_goals_conceded REAL NOT NULL,
    defensive_contribution INTEGER NOT NULL,
    PRIMARY KEY (ingestion_run_id, player_id)
);

CREATE INDEX IF NOT EXISTS player_snapshot_player_time_idx
ON player_snapshot(player_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS prediction_run (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ingestion_run_id INTEGER NOT NULL REFERENCES ingestion_run(id),
    source_hash TEXT NOT NULL,
    target_event INTEGER NOT NULL,
    model_version TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    assumptions TEXT NOT NULL,
    UNIQUE (source_hash, target_event, model_version)
);

CREATE TABLE IF NOT EXISTS player_prediction (
    prediction_run_id INTEGER NOT NULL REFERENCES prediction_run(id),
    player_id INTEGER NOT NULL REFERENCES player(fpl_id),
    expected_minutes REAL NOT NULL,
    expected_points REAL NOT NULL,
    expected_goals REAL NOT NULL,
    expected_assists REAL NOT NULL,
    clean_sheet_probability REAL NOT NULL,
    risk REAL NOT NULL,
    lower_bound REAL NOT NULL,
    upper_bound REAL NOT NULL,
    components TEXT NOT NULL,
    actual_points INTEGER,
    absolute_error REAL,
    squared_error REAL,
    evaluated_at TEXT,
    PRIMARY KEY (prediction_run_id, player_id)
);

CREATE TABLE IF NOT EXISTS player_prediction_evaluation (
    prediction_run_id INTEGER NOT NULL REFERENCES prediction_run(id),
    player_id INTEGER NOT NULL REFERENCES player(fpl_id),
    actual_points INTEGER NOT NULL,
    absolute_error REAL NOT NULL,
    squared_error REAL NOT NULL,
    evaluated_at TEXT NOT NULL,
    PRIMARY KEY (prediction_run_id, player_id)
);

CREATE TABLE IF NOT EXISTS prediction_evaluation (
    prediction_run_id INTEGER NOT NULL REFERENCES prediction_run(id),
    evaluation_policy TEXT NOT NULL,
    event_id INTEGER NOT NULL,
    deadline_time TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    players_evaluated INTEGER NOT NULL,
    mae REAL NOT NULL,
    rmse REAL NOT NULL,
    bias REAL NOT NULL,
    PRIMARY KEY (prediction_run_id, evaluation_policy)
);

CREATE INDEX IF NOT EXISTS prediction_event_idx
ON prediction_run(target_event, generated_at DESC);

CREATE TABLE IF NOT EXISTS manager_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    overall_rank INTEGER,
    total_points INTEGER,
    team_value INTEGER,
    bank INTEGER,
    payload TEXT NOT NULL,
    UNIQUE (entry_id, event_id, captured_at)
);

CREATE TABLE IF NOT EXISTS manager_pick (
    manager_snapshot_id INTEGER NOT NULL REFERENCES manager_snapshot(id),
    player_id INTEGER NOT NULL REFERENCES player(fpl_id),
    position INTEGER NOT NULL,
    multiplier INTEGER NOT NULL,
    is_captain INTEGER NOT NULL,
    is_vice_captain INTEGER NOT NULL,
    PRIMARY KEY (manager_snapshot_id, player_id)
);
