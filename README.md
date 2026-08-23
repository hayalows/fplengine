# FPL Engine

FPL Engine is an evidence-first Fantasy Premier League and Premier League intelligence
system. Version 0.2 is deliberately an engine, not a dashboard: it collects normalized
as-of snapshots, produces transparent and versioned expected-points forecasts, records
those forecasts before deadlines, and evaluates them against final FPL scores.

The recurring cash-cost target is **$0**. Neon Postgres is the intended production
system of record; SQLite is only the zero-setup local development cache.

## What v0.2 adds

- reads the current 2026/27 FPL bootstrap, fixture, event-live, entry, picks, history,
  and classic-league endpoints with timeouts and transient retries;
- preserves compact player, team, fixture, ownership, transfer, price, availability,
  and underlying-stat snapshots rather than retaining bulky raw JSON;
- estimates team goals, clean-sheet probability, expected minutes, expected goals,
  assists, defensive-contribution points, saves, cards, bonus, risk, uncertainty, and xP;
- handles blank and double gameweeks;
- ranks players, captains, value picks, differentials, and market movement;
- uses compact prior-season player and position evidence with explicit shrinkage;
- history-screens a prior-season top-1% candidate pool before forming an elite cohort;
- keeps predictions immutable and stores actuals and errors in separate evaluation tables;
- benchmarks GW6-38 against zero, last-GW, rolling-five, position-mean and archived-xP references;
- exposes a local CLI and dependency-free read-only JSON API;
- includes scheduled GitHub Actions ingestion with a safe no-op when the Neon secret is absent.

## Quick start

Python 3.11 or newer is required. The core engine has no third-party runtime dependency.

```powershell
$env:PYTHONPATH = "src"
python -m fplengine rankings --limit 20
python -m fplengine report --limit 10
python -m fplengine run --limit 15
python -m fplengine elite --sample 25 --candidate-pool 75 --minimum-past-seasons 2
python -m fplengine manager YOUR_PUBLIC_ENTRY_ID
python -m unittest discover -v
```

To use Neon after the migration is approved and applied:

```powershell
python -m pip install -e ".[postgres]"
$env:FPLENGINE_DATABASE_URL = "YOUR_NEON_POOLED_CONNECTION_STRING"
python -m fplengine run
```

Never commit the connection string. GitHub Actions expects it as the
`NEON_DATABASE_URL` repository secret.

Run the local API:

```powershell
$env:PYTHONPATH = "src"
python -m fplengine api --port 8000
```

Routes are `/health`, `/rankings`, `/report`, and `/manager/{entry_id}`. The server binds
to `127.0.0.1` by default and has no authentication, so it must not be exposed directly
to the public internet.

## Live GW2 verification snapshot

The engine was run against official FPL data on **2026-08-23 at 21:21 UTC**. The legacy
attack/defence strength fields were zero, so v0.2 used the still-populated ordinal
home/away team-strength fields rather than collapsing every fixture to the model floor.

| Rank | Player | Team | Pos | Expected minutes | GW2 xP | Ownership | Risk |
|---:|---|---|---|---:|---:|---:|---:|
| 1 | B. Fernandes | MUN | MID | 80.9 | 4.97 | 50.9% | 0.08 |
| 2 | Senesi | TOT | DEF | 86.6 | 4.80 | 8.2% | 0.03 |
| 3 | Szoboszlai | LIV | MID | 84.1 | 4.59 | 41.9% | 0.06 |
| 4 | Haaland | MCI | FWD | 82.0 | 4.54 | 69.1% | 0.04 |
| 5 | Virgil | LIV | DEF | 87.5 | 4.41 | 19.5% | 0.03 |
| 6 | Tavernier | BOU | MID | 76.3 | 4.34 | 1.7% | 0.09 |
| 7 | Mbeumo | MUN | MID | 72.4 | 4.13 | 37.9% | 0.12 |

A 25-manager live cohort was selected from 75 histories in FPL's official
`Top 1% 25/26 League`, requiring at least two ranked past seasons. Haaland was in 84% of
squads and captained by 44%; Fernandes was captained by 36%. This remains descriptive.

## Historical benchmark

The walk-forward 2025/26 benchmark forecasts GW6-38 using only earlier gameweeks and a
2024/25 prior. On 7,176 actual starters, v0.2 achieved MAE 2.360 and NDCG@10 0.396 versus
2.622 and 0.319 for the previous-five mean. Across all 25,750 player-gameweeks the rolling
mean retained lower MAE (1.046 versus 1.100), largely because non-playing zeros dominate.
The current range covered 69.5% of starters and is not a calibrated prediction interval.

## Architecture

```text
Official FPL public endpoints
        |
        v
resilient client -> normalized as-of observations -> Neon Postgres
        |                    |                         |
        |                    v                         v
        +----------> feature/model layer ------> versioned predictions
                                             \-> post-GW evaluation
                                                      |
                                    CLI / local JSON API / future optimizer
```

See [Architecture](docs/ARCHITECTURE.md), [data-source decisions](docs/DATA_SOURCES.md),
[model card](docs/MODEL_CARD.md), [research](docs/RESEARCH.md), and
[Azure audit](docs/AZURE.md).

## Evidence labels

Every decision output distinguishes:

- **observed**: values read from an FPL endpoint at a recorded timestamp;
- **third-party**: supplied ratings such as FPL team strengths;
- **calculated**: deterministic features such as market momentum or value;
- **prediction**: uncertain future estimates such as xMins and xP;
- **assumption**: priors or structural choices not established by the data.

## Current boundary

This is a benchmarked challenger, not proof of live-season superiority. No 2026/27
gameweek has yet been evaluated from a preserved pre-deadline v0.2 forecast. Interval
calibration, promoted/new-signing priors, bonus and transfer-sensitive role changes remain.
