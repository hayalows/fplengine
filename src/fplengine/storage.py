"""Persistence for local verification and Neon Postgres production use."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import unquote

from .api_client import Snapshot
from .model import Prediction


DEFAULT_SQLITE_PATH = Path(".data/fplengine.db")


def database_url(explicit: str | None = None) -> str:
    return explicit or os.getenv("FPLENGINE_DATABASE_URL") or f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"


class Store:
    def __init__(self, url: str | None = None) -> None:
        self.url = database_url(url)
        self.is_postgres = self.url.startswith(("postgresql://", "postgres://"))
        if not self.is_postgres and not self.url.startswith("sqlite:///"):
            raise ValueError("Database URL must use postgresql:// or sqlite:///")
        self.schema = os.getenv("FPLENGINE_DB_SCHEMA", "engine")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.schema):
            raise ValueError("Database schema must be a simple SQL identifier")

    def _table(self, name: str) -> str:
        return f"{self.schema}.{name}" if self.is_postgres else name

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.is_postgres else statement

    @contextmanager
    def connect(self) -> Iterator[Any]:
        if self.is_postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError(
                    "Postgres requires the optional dependency: pip install -e .[postgres]"
                ) from exc
            connection = psycopg.connect(self.url, row_factory=dict_row)
        else:
            raw_path = unquote(self.url.removeprefix("sqlite:///"))
            if raw_path.startswith("/") and len(raw_path) > 3 and raw_path[2] == ":":
                raw_path = raw_path[1:]
            path = Path(raw_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        migration_name = "001_postgres.sql" if self.is_postgres else "001_sqlite.sql"
        migration = files("fplengine").joinpath("migrations", migration_name).read_text("utf-8")
        with self.connect() as connection:
            if self.is_postgres:
                connection.execute(migration, prepare=False)
            else:
                connection.executescript(migration)

    @staticmethod
    def _current_event(snapshot: Snapshot) -> int | None:
        current = next(
            (row for row in snapshot.bootstrap["events"] if row.get("is_current")), None
        )
        return int(current["id"]) if current else None

    def save_snapshot(self, snapshot: Snapshot) -> tuple[int, bool]:
        """Normalize one API snapshot. Returns (ingestion_id, was_inserted)."""
        fetched_at = snapshot.fetched_at.isoformat()
        ingestion = self._table("ingestion_run")
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                self._sql(
                    f"""INSERT INTO {ingestion}
                    (source_hash, source_name, fetched_at, status, player_count, team_count,
                     fixture_count, observed_event)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (source_hash) DO NOTHING"""
                ),
                (
                    snapshot.source_hash,
                    "official-fpl-public-endpoints",
                    fetched_at,
                    "succeeded",
                    len(snapshot.bootstrap["elements"]),
                    len(snapshot.bootstrap["teams"]),
                    len(snapshot.fixtures),
                    self._current_event(snapshot),
                ),
            )
            inserted = cursor.rowcount > 0
            cursor.execute(
                self._sql(f"SELECT id FROM {ingestion} WHERE source_hash = ?"),
                (snapshot.source_hash,),
            )
            row = cursor.fetchone()
            ingestion_id = int(row["id"] if hasattr(row, "keys") else row[0])
            if not inserted:
                return ingestion_id, False

            teams_sql = self._sql(
                f"""INSERT INTO {self._table('team')}
                (fpl_id, code, name, short_name, updated_at) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (fpl_id) DO UPDATE SET code=excluded.code, name=excluded.name,
                short_name=excluded.short_name, updated_at=excluded.updated_at"""
            )
            cursor.executemany(
                teams_sql,
                [
                    (int(row["id"]), int(row["code"]), row["name"], row["short_name"], fetched_at)
                    for row in snapshot.bootstrap["teams"]
                ],
            )
            players_sql = self._sql(
                f"""INSERT INTO {self._table('player')}
                (fpl_id, fpl_code, opta_code, first_name, second_name, web_name,
                 position_id, team_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (fpl_id) DO UPDATE SET fpl_code=excluded.fpl_code,
                opta_code=excluded.opta_code, first_name=excluded.first_name,
                second_name=excluded.second_name, web_name=excluded.web_name,
                position_id=excluded.position_id, team_id=excluded.team_id,
                updated_at=excluded.updated_at"""
            )
            cursor.executemany(
                players_sql,
                [
                    (
                        int(row["id"]),
                        int(row.get("code") or 0),
                        row.get("opta_code"),
                        row.get("first_name") or "",
                        row.get("second_name") or "",
                        row["web_name"],
                        int(row["element_type"]),
                        int(row["team"]),
                        fetched_at,
                    )
                    for row in snapshot.bootstrap["elements"]
                ],
            )
            fixture_sql = self._sql(
                f"""INSERT INTO {self._table('fixture')}
                (fpl_id, event_id, kickoff_time, home_team_id, away_team_id, home_score,
                 away_score, started, finished, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (fpl_id) DO UPDATE SET event_id=excluded.event_id,
                kickoff_time=excluded.kickoff_time, home_team_id=excluded.home_team_id,
                away_team_id=excluded.away_team_id, home_score=excluded.home_score,
                away_score=excluded.away_score, started=excluded.started,
                finished=excluded.finished, updated_at=excluded.updated_at"""
            )
            cursor.executemany(
                fixture_sql,
                [
                    (
                        int(row["id"]),
                        row.get("event"),
                        row.get("kickoff_time"),
                        int(row["team_h"]),
                        int(row["team_a"]),
                        row.get("team_h_score"),
                        row.get("team_a_score"),
                        bool(row.get("started")),
                        bool(row.get("finished")),
                        fetched_at,
                    )
                    for row in snapshot.fixtures
                ],
            )
            snapshot_sql = self._sql(
                f"""INSERT INTO {self._table('player_snapshot')}
                (ingestion_run_id, player_id, captured_at, now_cost, selected_percent,
                 status, chance_next, news, minutes, starts, total_points, event_points,
                 transfers_in_event, transfers_out_event, expected_goals, expected_assists,
                 expected_goals_conceded, defensive_contribution)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            )
            cursor.executemany(
                snapshot_sql,
                [
                    (
                        ingestion_id,
                        int(row["id"]),
                        fetched_at,
                        int(row["now_cost"]),
                        float(row.get("selected_by_percent") or 0),
                        row.get("status") or "",
                        row.get("chance_of_playing_next_round"),
                        row.get("news") or "",
                        int(row.get("minutes") or 0),
                        int(row.get("starts") or 0),
                        int(row.get("total_points") or 0),
                        int(row.get("event_points") or 0),
                        int(row.get("transfers_in_event") or 0),
                        int(row.get("transfers_out_event") or 0),
                        float(row.get("expected_goals") or 0),
                        float(row.get("expected_assists") or 0),
                        float(row.get("expected_goals_conceded") or 0),
                        int(row.get("defensive_contribution") or 0),
                    )
                    for row in snapshot.bootstrap["elements"]
                ],
            )
        return ingestion_id, True

    def save_predictions(
        self, ingestion_id: int, snapshot: Snapshot, predictions: Sequence[Prediction]
    ) -> int:
        if not predictions:
            raise ValueError("Cannot persist an empty prediction set")
        first = predictions[0]
        generated_at = datetime.now(timezone.utc).isoformat()
        assumptions = json.dumps(first.provenance, sort_keys=True)
        runs = self._table("prediction_run")
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                self._sql(
                    f"""INSERT INTO {runs}
                    (ingestion_run_id, source_hash, target_event, model_version,
                     generated_at, assumptions) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (source_hash, target_event, model_version) DO NOTHING"""
                ),
                (
                    ingestion_id,
                    snapshot.source_hash,
                    first.target_event,
                    first.model_version,
                    generated_at,
                    assumptions,
                ),
            )
            cursor.execute(
                self._sql(
                    f"SELECT id FROM {runs} WHERE source_hash=? AND target_event=? AND model_version=?"
                ),
                (snapshot.source_hash, first.target_event, first.model_version),
            )
            row = cursor.fetchone()
            run_id = int(row["id"] if hasattr(row, "keys") else row[0])
            sql = self._sql(
                f"""INSERT INTO {self._table('player_prediction')}
                (prediction_run_id, player_id, expected_minutes, expected_points,
                 expected_goals, expected_assists, clean_sheet_probability, risk,
                 lower_bound, upper_bound, components)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (prediction_run_id, player_id) DO UPDATE SET
                expected_minutes=excluded.expected_minutes,
                expected_points=excluded.expected_points,
                expected_goals=excluded.expected_goals,
                expected_assists=excluded.expected_assists,
                clean_sheet_probability=excluded.clean_sheet_probability,
                risk=excluded.risk, lower_bound=excluded.lower_bound,
                upper_bound=excluded.upper_bound, components=excluded.components"""
            )
            cursor.executemany(
                sql,
                [
                    (
                        run_id,
                        row.player_id,
                        row.expected_minutes,
                        row.expected_points,
                        row.expected_goals,
                        row.expected_assists,
                        row.clean_sheet_probability,
                        row.risk,
                        row.lower_bound,
                        row.upper_bound,
                        json.dumps(row.components, sort_keys=True),
                    )
                    for row in predictions
                ],
            )
        return run_id

    def evaluate(
        self, event_id: int, actual_points: dict[int, int], deadline_utc: str
    ) -> dict[str, float | int]:
        runs = self._table("prediction_run")
        predictions = self._table("player_prediction")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(
                self._sql(
                    f"""SELECT id FROM {runs}
                    WHERE target_event=? AND generated_at <= ?
                    ORDER BY generated_at ASC LIMIT 1"""
                ),
                (event_id, deadline_utc),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"No pre-deadline prediction run exists for GW{event_id}")
            run_id = int(row["id"] if hasattr(row, "keys") else row[0])
            cursor.execute(
                self._sql(f"SELECT player_id, expected_points FROM {predictions} WHERE prediction_run_id=?"),
                (run_id,),
            )
            rows = cursor.fetchall()
            errors: list[float] = []
            for prediction in rows:
                player_id = int(prediction["player_id"])
                if player_id not in actual_points:
                    continue
                expected = float(prediction["expected_points"])
                actual = int(actual_points[player_id])
                error = actual - expected
                errors.append(error)
                cursor.execute(
                    self._sql(
                        f"""UPDATE {predictions} SET actual_points=?, absolute_error=?,
                        squared_error=?, evaluated_at=? WHERE prediction_run_id=? AND player_id=?"""
                    ),
                    (actual, abs(error), error * error, now, run_id, player_id),
                )
        if not errors:
            raise ValueError(f"No actual player scores matched the GW{event_id} prediction run")
        return {
            "prediction_run_id": run_id,
            "players_evaluated": len(errors),
            "mae": round(sum(abs(value) for value in errors) / len(errors), 4),
            "rmse": round(math.sqrt(sum(value * value for value in errors) / len(errors)), 4),
            "bias": round(sum(errors) / len(errors), 4),
        }
