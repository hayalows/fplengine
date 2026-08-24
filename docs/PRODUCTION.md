# Production activation runbook

This document records the production boundary for FPL Engine and the checks required before scheduled writes are considered live.

## Current state

- Neon project: `fpl-lab`
- Production branch: `main`
- Application schema: `engine`
- Production migration applied and verified on 2026-08-24
- Existing unrelated `public.fpl_snapshots` table remains untouched
- GitHub repository and CI are live
- Scheduled ingestion workflow exists but intentionally performs a safe no-op until `NEON_DATABASE_URL` is configured
- Production `engine` tables are currently empty, which is the expected state before the first production ingestion

## Security boundary

A database-owner connection string was exposed during an earlier private tool-assisted migration test. Do not place that credential in GitHub Actions or any long-lived environment.

Before activating the scheduler:

1. Rotate the exposed `neondb_owner` credential in Neon.
2. Prefer a dedicated application role for FPL Engine rather than the database owner.
3. Grant that role only the permissions required to read and write the `engine` schema.
4. Use a pooled Neon connection string with TLS required.
5. Store the replacement connection string only as the GitHub Actions repository secret `NEON_DATABASE_URL`.
6. Never commit a real connection string to the repository, workflow files, logs, reports, or issues.

## First production run

After the secret is configured, manually dispatch `FPL ingestion and evaluation` once before relying on the six-hour schedule.

The run is successful only if all of the following are true:

- the workflow completes without exposing credentials;
- one ingestion run is persisted for the current canonical source hash;
- 20 teams and the current FPL player universe are present;
- all 380 league fixtures are present when the official feed exposes the complete schedule;
- a versioned prediction run is stored for the next actionable gameweek;
- player predictions reference that prediction run;
- `evaluate-latest` either evaluates a genuinely final gameweek with a pre-deadline forecast or explicitly reports a safe skip;
- rerunning the workflow against an unchanged source does not create a duplicate ingestion or prediction run.

## Idempotency check

Run the workflow twice while the official FPL payload is unchanged. The second run should reuse the same canonical source snapshot and model-version prediction rather than creating duplicate historical facts.

A changing official payload is not a failed idempotency test. Price, ownership, transfer, availability, fixture-status, or other source changes should produce a new canonical snapshot.

## Data-quality checks

For each production run, monitor at minimum:

- player count and unexpected changes;
- team count;
- fixture count;
- target gameweek;
- prediction count;
- source hash;
- model version;
- capture time and prediction-generation time;
- missing or implausible expected minutes;
- prediction ranges and risk values;
- schema/API drift warnings.

A large count change or field disappearance should fail visibly rather than silently producing rankings.

## Storage budget

The recurring cash-cost target remains $0. Keep compact normalized observations in Neon and keep bulky historical research archives outside the production database.

Measure actual row growth before implementing deletion. When retention becomes necessary, preserve every pre-deadline prediction and evaluation permanently and downsample only redundant intra-day observations according to measured storage pressure.

## Recovery

If a production ingestion fails:

1. do not delete the last successful prediction;
2. diagnose the source/schema error first;
3. keep failed or partial source data from replacing a valid snapshot;
4. use a Neon branch for any schema repair or risky data correction;
5. verify the repair on the branch before promoting it to production.

## Activation definition

Production is considered fully active only after the rotated/dedicated credential is configured, one manual GitHub Actions ingestion succeeds against Neon `main`, a second unchanged-payload run demonstrates idempotency, and the next scheduled run succeeds without intervention.
