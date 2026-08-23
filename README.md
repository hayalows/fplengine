# FPL Engine

FPL Engine is an evidence-first Fantasy Premier League and Premier League intelligence
system. Version 0.1 is deliberately an engine, not a dashboard: it collects normalized
as-of snapshots, produces transparent and versioned expected-points forecasts, records
those forecasts before deadlines, and evaluates them against final FPL scores.

The recurring cash-cost target is **$0**. Neon Postgres is the intended production
system of record; SQLite is only the zero-setup local development cache.

## What v0.1 does

- reads the current 2026/27 FPL bootstrap, fixture, event-live, entry, picks, history,
  and classic-league endpoints with timeouts and transient retries;
- preserves compact player, team, fixture, ownership, transfer, price, availability,
  and underlying-stat snapshots rather than retaining bulky raw JSON;
- estimates team goals, clean-sheet probability, expected minutes, expected goals,
  assists, defensive-contribution points, saves, cards, bonus, risk, uncertainty, and xP;
- handles blank and double gameweeks;
- ranks players, captains, value picks, differentials, and market movement;
- analyses a public FPL team and a bounded prior-season top-1% manager cohort;
- versions every prediction and stores the component breakdown and assumptions;
- evaluates only pre-deadline prediction runs after FPL marks a gameweek final;
- exposes a local CLI and dependency-free read-only JSON API;
- includes scheduled GitHub Actions ingestion with a safe no-op when the Neon secret is absent.

## Quick start

Python 3.11 or newer is required. The core engine has no third-party runtime dependency.

```powershell
$env:PYTHONPATH = "src"
python -m fplengine rankings --limit 20
python -m fplengine report --limit 10
python -m fplengine run --limit 15
python -m fplengine elite --sample 10
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
to `127.0.0.1` by default and has no authentication, so v0.1 must not be exposed directly
to the public internet.

## Live verification snapshot

The engine was run against official FPL data on **2026-08-23 at 19:50 UTC**. GW1 was
still in progress, so the actionable target was GW2 and every leading forecast was
correctly labeled low-confidence.

| Rank | Player | Team | Pos | Expected minutes | GW2 xP | Ownership | Risk |
|---:|---|---|---|---:|---:|---:|---:|
| 1 | Szoboszlai | LIV | MID | 71.0 | 4.23 | 41.9% | 0.09 |
| 2 | Calvert-Lewin | LEE | FWD | 68.3 | 3.97 | 30.6% | 0.12 |
| 3 | Mbeumo | MUN | MID | 72.0 | 3.94 | 38.0% | 0.08 |
| 4 | Isak | LIV | FWD | 67.3 | 3.89 | 17.0% | 0.13 |
| 5 | Kinsky | TOT | GK | 69.9 | 3.85 | 23.9% | 0.16 |
| 6 | B. Fernandes | MUN | MID | 76.3 | 3.79 | 50.9% | 0.04 |
| 7 | Haaland | MCI | FWD | 77.8 | 3.78 | 69.1% | 0.02 |

A separate 10-manager read from FPL's official `Top 1% 25/26 League` found Haaland in
10/10 squads and captained by 6/10. That is descriptive cohort consensus, not proof that
copying it improves performance.

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

This is a working baseline, not a claim of predictive superiority. It has not yet been
trained on a historical as-of dataset or evaluated over completed 2026/27 gameweeks.
The early-season priors, bonus approximation, and current team-strength calibration are
the most important model risks. See the model card and roadmap for the falsification plan.
