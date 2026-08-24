# Highest-value roadmap

## 1. Establish a real evaluation baseline

- collect deadline-minus-24h and last-pre-deadline predictions for every gameweek;
- score MAE, RMSE, bias, rank correlation, calibration, captain regret, and top-decile precision;
- compare with FPL `ep_next`, ownership, position mean, and rolling-points baselines;
- publish weekly model cards without claiming success from tiny samples.

The 2025/26 replay is evidence that v0.2 is a useful challenger, not proof of live-season superiority. The strongest evidence now must come from predictions that were genuinely captured before 2026/27 deadlines.

## 2. Build the historical as-of dataset

- review and pin source licenses/attribution;
- make up to roughly ten completed FPL seasons available where reliable gameweek data exists;
- import historical FPL gameweek files with stable code mappings and source hashes;
- reconstruct only information knowable at each deadline;
- add a data-quality report for missing players, duplicate fixtures, corrections, rule changes, and IDs;
- keep bulky raw archives outside Neon and persist only reproducible compact features, model metadata, predictions, and evaluation results.

Historical depth is an experiment, not a fixed assumption. Compare one-, two-, three-, five-, seven-, and approximately ten-season windows plus recency-weighted variants. Use walk-forward validation and let held-out performance determine how much history each model component deserves to remember.

## 3. Model role transitions explicitly

The clearest current model risk is stale role evidence after transfers, promotion, new signings, manager changes, and abrupt starter-status changes.

- identify historical same-club continuations, same-league transfers, promoted-team players, new Premier League arrivals, manager changes, and starter/substitute transitions;
- measure how quickly prior-season minutes and attacking/defensive rates remain predictive after each transition type;
- test explicit prior decay and wider uncertainty for transition cases;
- keep an untouched held-out season for choosing between transition policies;
- reject a transition model if it does not improve decision-facing ranking/calibration metrics.

## 4. Replace remaining weak priors

- train expected-minutes role models from starts, substitutions, injuries, schedule density, and transition state;
- fit time-decayed team attack/defence plus home advantage and a Dixon-Coles challenger;
- calibrate player xG/xA share and defensive-contribution threshold probability;
- implement the full current BPS rules or learn bonus conditional on observable components;
- calibrate uncertainty separately for likely starters, cameo candidates, and the full player population.

Do not promote a more complex model unless it improves held-out decision metrics over simple baselines and the current production model.

## 5. Multi-week transfer optimization

- integer-program a legal 15-player squad and XI under budget, formation, club limit,
  transfers, hits, bank, free-transfer carry, chips, and horizon uncertainty;
- model scenarios for injury, rotation, blank/double gameweeks, and price movement;
- distinguish expected-value recommendations from risk-seeking or rank-protection strategies;
- show regret and sensitivity rather than a single falsely precise “optimal” answer.

## 6. Operational hardening

- [x] validate the corrected Neon migration on an isolated branch;
- [x] apply the validated `engine` schema to Neon production `main`;
- [ ] rotate the previously exposed database-owner credential;
- [ ] prefer a dedicated least-privilege FPL Engine database role;
- [ ] configure GitHub Actions `NEON_DATABASE_URL` with the replacement pooled connection string;
- [ ] manually dispatch and verify the first production ingestion;
- [ ] rerun against an unchanged payload to demonstrate production idempotency;
- [ ] verify the next scheduled six-hour run without intervention;
- [ ] add schema-drift contract tests against captured fixtures;
- [ ] measure Neon row growth and implement evidence-based downsampling only when required;
- [ ] add authenticated API hosting only when there is a real consumer.

See [PRODUCTION.md](PRODUCTION.md) for the activation and recovery runbook.
