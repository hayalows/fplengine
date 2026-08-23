# Model card: `xp-v0.1.0`

## Intended use

Rank FPL players for the next actionable gameweek and expose a transparent baseline for
captain, value, differential, market, and manager-team analysis. It is an engineering
and research baseline, not betting advice or a guaranteed rank-improvement system.

## Inputs

- observed FPL player minutes, starts, price, ownership, availability, status, transfers,
  saves, cards, xG, xA, expected goals conceded, and defensive contributions;
- current fixtures and home/away team identity;
- FPL-calculated team attack and defence strength ratings;
- position priors and explicit structural assumptions.

The model does not use paid feeds, paid AI, scraped news, bookmaker odds, or FPL's
`ep_next` field as its prediction target or shortcut.

## Method

1. Estimate start probability from starts plus a three-match prior informed by observed
   ownership, price within position, and set-piece ordering.
2. Shrink minutes per start to position defaults.
3. Shrink xG, xA, and defensive-action rates with 450 prior minutes.
4. Estimate team goals from home/away FPL team-strength ratios and Poisson assumptions.
5. Allocate 86% of team goals and 74% of team assists across players by rate and xMins.
6. Calculate FPL appearance, goal, assist, clean-sheet, save, defensive-contribution,
   approximate bonus, goals-conceded, and card components.
7. Return xP, range, risk, value, differential score, and full component provenance.

Defensive contributions follow the official 2026/27 rules: two points at 10 CBIT for
defenders or 12 CBIRT for midfielders/forwards, capped per fixture.

## Known limitations

- Early-season roles are weakly identified. Ownership and price are noisy role proxies.
- Team strength is not yet estimated from historical match results or an xG model.
- Bonus is an approximation and does not implement the complete 2026/27 BPS event model.
- Goal/assist allocations are team-coherent but not yet learned from player history.
- Injury/team-news data is limited to official FPL status/news.
- Uncertainty bounds are heuristic, not empirically calibrated quantiles.
- Correlation between player returns and match states is not simulated.

## Validation status

Verified in v0.1:

- blank gameweeks produce zero fixtures and zero xP;
- double-gameweek minutes and components accumulate;
- unavailable players receive no minutes or attacking allocation;
- live team/player counter lag cannot create a greater-than-one start probability;
- outputs are ranked, finite, versioned, and range-consistent;
- source/prediction persistence is idempotent;
- manager cohort percentages use only successfully read entries;
- the complete model ran on 609 live players and 380 fixtures.

Not yet verified:

- out-of-sample MAE/RMSE/calibration over a completed gameweek;
- superiority to simple baselines such as last-season points, FPL `ep_next`, ownership,
  or betting-implied team goals;
- captain hit rate, transfer value added, or rank improvement.

## Falsification plan

For each final gameweek, compare at least:

- `xp-v0.1.0`;
- FPL `ep_next` captured pre-deadline;
- naive position mean;
- rolling points-per-90 with minutes shrinkage;
- ownership-only ranking.

Report MAE, RMSE, bias, Spearman rank correlation, top-decile precision, calibration by
xP bucket, and captain regret. Replace or recalibrate this model if it cannot beat the
simple baselines over a meaningful sequence of gameweeks.
