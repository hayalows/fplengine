# Architecture

## Decision summary

The smallest architecture that satisfies the long-term objective is a modular Python
engine with a normalized Postgres history, deterministic feature generation, versioned
models, deadline-aware evaluation, a CLI, and a read API. A frontend, message broker,
data lake, and Azure compute were intentionally deferred because none improves v0.1's
decision quality enough to justify the operational or cost surface.

## Components

| Component | Responsibility | Current implementation |
|---|---|---|
| Source client | Polite HTTP reads, validation, retries | `api_client.py` |
| Observation store | Compact as-of facts and provenance | Neon migration plus local SQLite parity |
| Baseline model | xMins, xG/xA allocation, xP, uncertainty | `model.py` |
| Decision services | rankings, captaincy, value, managers | `service.py` |
| Interfaces | repeatable CLI and read API | `cli.py`, `http_api.py` |
| Evaluation | actuals, MAE, RMSE, bias | deadline-guarded persistence method |
| Scheduling | ingestion and final-GW evaluation | GitHub Actions every six hours |

## Persistent model

Neon is the production system of record. The existing `fpl-lab` project was inspected
and had one unrelated `public.fpl_snapshots` table. FPL Engine therefore uses its own
`engine` schema and does not alter that table.

The schema preserves:

- stable FPL player ID, FPL player code, and Opta code where supplied;
- current player/team dimensions separately from timestamped observations;
- one ingestion row per unique canonical source hash;
- compact player snapshots for price, ownership, transfers, availability, minutes,
  starts, scoring, xG/xA, expected goals conceded, and defensive contributions;
- fixtures with stable FPL IDs and current scheduling/status;
- a prediction run keyed by source hash, target event, and model version;
- component-level player predictions and post-event error metrics;
- manager/pick tables ready for cohort history.

Raw bootstrap JSON is not retained in Postgres. The hash, counts, normalized fields, and
timestamps provide reproducibility while protecting the existing free-tier storage.

## Idempotency and resilience

The canonical hash covers bootstrap and fixture payloads. Re-reading identical source
data returns the existing ingestion run and prediction run. Database upserts are keyed
by stable external IDs. HTTP failures time out and retry only transient/network errors;
permanent 4xx errors fail explicitly.

GitHub Actions has a concurrency group, does not cancel an active ingestion, stores no
artifacts, and exits successfully without a database secret. A failed run cannot silently
replace a prior successful prediction.

## Leakage controls

1. Every observation has `captured_at` and every prediction has `generated_at`.
2. The feature/model layer receives one immutable snapshot rather than querying current
   values during calculation.
3. Evaluation chooses a prediction generated on or before the gameweek deadline.
4. FPL event actuals are read only after the bootstrap marks that gameweek final.
5. Future historical training must use features reconstructable at each historical
   deadline; end-of-season summaries must not be joined backward.

The first-prediction evaluation policy is conservative. Future versions should evaluate
both a fixed deadline-minus-24h run and the last pre-deadline run.

## Storage budget

At four ingestions per day, 609 players produce roughly 73,000 compact player snapshots
per month. Even with indexes, this is compatible with a 512 MB project only if retention
is managed. The initial policy is:

- keep every snapshot around deadlines and price-change windows;
- later downsample unchanged intra-day snapshots older than eight weeks;
- retain every prediction and evaluation permanently;
- never store duplicated raw payloads in Postgres.

No retention deletion is implemented in v0.1; it should be added only after measured
row-size and growth evidence exists.

## Extension seams

- historical importer with explicit license/provenance mapping;
- time-decayed team attack/defence posterior and Dixon-Coles score simulation;
- expected-minutes model trained on as-of lineups and availability;
- integer-programming transfer planner across multiple gameweeks;
- model registry/challenger evaluation and calibration dashboards;
- authenticated public API deployment after a real hosting decision.
