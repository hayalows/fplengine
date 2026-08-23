# Model card: `xp-v0.2.0`

## Intended use

Rank FPL players for the next actionable gameweek and expose a transparent baseline for
captain, value, differential, market, and manager-team analysis. It is an engineering
and research baseline, not betting advice or a guaranteed rank-improvement system.

## Inputs

- observed FPL player minutes, starts, price, ownership, availability, status, transfers,
  saves, cards, xG, xA, expected goals conceded, and defensive contributions;
- current fixtures and home/away team identity;
- FPL ordinal home/away strength ratings, used because the legacy attack/defence fields
  are currently zero in the live feed;
- compact previous-season player, position and role aggregates keyed by stable FPL code.

The model does not use paid feeds, paid AI, scraped news, bookmaker odds, or FPL's
`ep_next` field as its prediction target or shortcut.

## Method

1. Estimate coherent probabilities of any appearance and 60+ minutes from current starts,
   prior-season starts/substitute use and availability. Ownership is not a minutes input.
2. Shrink minutes per start/cameo to player-history and position evidence.
3. Hierarchically shrink xG, xA, saves, defensive actions, bonus and card rates.
4. Estimate team goals from ordinal home/away strengths and Poisson assumptions.
5. Allocate 86% of team goals and 74% of team assists across players by rate and xMins.
6. Calculate FPL appearance, goal, assist, clean-sheet, save, defensive-contribution,
   approximate bonus, goals-conceded, and card components.
7. Return xP, range, risk, value, differential score, and full component provenance.

Defensive contributions follow the official 2026/27 rules: two points at 10 CBIT for
defenders or 12 CBIRT for midfielders/forwards, capped per fixture.

## Known limitations

- Transfers, manager changes, new signings and promoted teams can break role persistence.
- Ordinal team strengths are coarse; the previous-season team-xG challenger did not earn
  promotion because it reduced ranking quality.
- Bonus is an approximation and does not implement the complete 2026/27 BPS event model.
- Goal/assist allocations are team-coherent but not yet learned from player history.
- Injury/team-news data is limited to official FPL status/news.
- Uncertainty bounds are heuristic and covered only 69.5% of historical starters.
- Correlation between player returns and match states is not simulated.

## Validation status

Verified in v0.2:

- blank gameweeks produce zero fixtures and zero xP;
- double-gameweek minutes and components accumulate;
- unavailable players receive no minutes or attacking allocation;
- live team/player counter lag cannot create a greater-than-one start probability;
- outputs are ranked, finite, versioned, and range-consistent;
- source/prediction persistence is idempotent;
- manager cohort percentages use only successfully read entries;
- the complete model ran on 609 live players and 380 fixtures;
- forecasts remain immutable while outcomes are stored separately;
- a real `xp-v0.2.0` pipeline persisted on an isolated Neon branch;
- the benchmark covered GW6-38, 25,750 player-gameweeks and 7,176 starters.

The historical benchmark is time-ordered within one archive, but is not a fully untouched
test set because v0.2 decisions were made after reading the season-level report. Live
pre-deadline evaluation, captain regret, transfer value and rank improvement remain unverified.

## Falsification plan

For each final gameweek, compare immutable earliest- and latest-predeadline `xp-v0.2.0`
runs with zero, last-gameweek, position mean, rolling-five mean and genuinely captured
predeadline FPL xP.

Report MAE, RMSE, bias, Spearman rank correlation, top-decile precision, calibration by
xP bucket, and captain regret. Replace or recalibrate this model if it cannot beat the
simple baselines over a meaningful sequence of gameweeks.
