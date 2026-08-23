# Highest-value roadmap

## 1. Establish a real evaluation baseline

- collect deadline-minus-24h and last-pre-deadline predictions for every gameweek;
- score MAE, RMSE, bias, rank correlation, calibration, captain regret, and top-decile precision;
- compare with FPL `ep_next`, ownership, position mean, and rolling-points baselines;
- publish weekly model cards without claiming success from tiny samples.

## 2. Build the historical as-of dataset

- review and pin source licenses/attribution;
- import historic FPL gameweek files with stable code mappings and source hashes;
- reconstruct only information knowable at each deadline;
- add a data-quality report for missing players, duplicate fixtures, corrections, and IDs.

## 3. Replace weak priors

- train expected-minutes survival/role models from starts, substitutions, injuries, and schedule density;
- fit time-decayed team attack/defence plus home advantage and Dixon-Coles correction;
- calibrate player xG/xA share and defensive-contribution threshold probability;
- implement the full current BPS rules or learn bonus conditional on observable components.

## 4. Multi-week transfer optimization

- integer-program a legal 15-player squad and XI under budget, formation, club limit,
  transfers, hits, bank, free-transfer carry, chips, and horizon uncertainty;
- model scenarios for injury, rotation, blank/double gameweeks, and price movement;
- show regret and sensitivity rather than a single falsely precise “optimal” answer.

## 5. Operational hardening

- approve and apply the corrected Neon migration through a fresh temporary-branch workflow;
- configure `NEON_DATABASE_URL` and a $0 GitHub Actions budget/usage guard;
- add schema-drift contract tests against captured fixtures;
- measure Neon row growth and implement evidence-based downsampling;
- add authenticated API hosting only when there is a real consumer.
