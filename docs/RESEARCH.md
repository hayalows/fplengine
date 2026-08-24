# Research findings

Research was refreshed on 2026-08-23 and favored primary/official sources.

## Team-model correctness audit (2026-08-24, supersedes v0.1 numbers)

A focused audit of `team_model` found and fixed real defects before any tuning:

1. **Fitting equations were wrong.** Derivation plus a numerical-gradient probe showed
   max |dL/dparam| ~ 53 at the returned solution: exp(home_advantage) was missing from
   the attack exposure of home fixtures and the defence exposure of away fixtures.
   Both coordinate updates now implement the exact stationarity conditions; tests add
   finite-difference gradient checks (~0 at optimum), monotone likelihood across
   sweeps, and lambda recovery from simulated known parameters (<10% mean error).
2. **Training data was silently incomplete.** 2019/20 contains 92 genuine finished
   fixtures stored with event values beyond 38 (COVID rescheduling); the old loader's
   `event <= 38` filter dropped them, producing 2,188 instead of 2,280 training
   matches. The loader now accepts finished matches regardless of event number,
   deduplicates on (home, away, kickoff), and emits a per-season acceptance audit.
   Corrected training count: 2,280/2,280 with zero unexplained rejections.
3. **Promoted/unseen teams vanished from evaluation** (7 of 380 holdout matches).
   Forecasts for unseen teams now use an explicit shrunk league-average prior
   (mean-centred attack 0.0, mean fitted defence), flagged per prediction via
   `priors_used`. All 380 holdout matches are now evaluated, including GW1.
4. **Club identity** is name-based because archive team IDs are reassigned between
   seasons; a tested canonical alias table (`CANONICAL_TEAM_ALIASES`) collapses known
   spellings ("Man City"/"Manchester City", "Spurs", "Nott'm Forest", ...). Within the
   loaded 2019/20-2025/26 window names proved already consistent; the table protects
   future recovery of earlier eras.

Corrected frozen baseline (untouched 2025/26 holdout, refresh every 60):

| Slice | n | Log loss | Brier | Accuracy |
|---|---|---|---|---|
| All matches | 380 | **1.0396** | **0.6251** | **46.6%** |
| Prior-backed (unseen-team) only | 6 | 1.139 | 0.696 | 16.7% |
| Events <= 6 (early season) | 60 | 1.031 | 0.615 | 45.0% |
| Events > 6 | 320 | 1.041 | 0.627 | 46.9% |
| Train-rate baseline | 380 | 1.0837 | 0.6557 | 42.6% |
| Uniform baseline | 380 | 1.0986 | 0.6667 | 42.6% |

The previous headline result survives and slightly improves despite adding the seven
hardest matches. Honest weakness: the six prior-backed Sunderland forecasts underperformed
even uniform (n too small to conclude); a mildly pessimistic promoted-team prior is the
next candidate experiment, after this corrected baseline is frozen. Dixon-Coles selected
rho = -0.05; fitted home advantage ~ +17% goals. Artifact:
`reports/team_strength_backtest.json`.

## Team strength / match probability module v0.1 (2026-08-24)

New standalone `fplengine.team_model`: Maher-style weighted Poisson attack/defence
ratings plus a fitted home-advantage term, optional Dixon-Coles low-score correction,
closed-form coordinate ascent fitting (no third-party dependencies), and a
walk-forward backtester that refits only on strictly earlier matches.

First held-out evaluation: train on 2019/20-2024/25 archive results (2,283 matches;
earlier seasons lack fixture files), walk-forward through the untouched 2025/26
season with ratings refreshed every 60 matches:

| Model | Log loss | Brier | Accuracy |
|---|---|---|---|
| Poisson ratings | **1.042** | **0.627** | **45.6%** |
| Train-window outcome rates | 1.084 | 0.656 | 42.4% |
| Uniform 1/3 | 1.099 | 0.667 | 42.4% |

The ratings beat both baselines on every metric but the margin over simple historical
frequencies is small; Dixon-Coles rho selected 0.0 and fitted home advantage is about
+7.6% goals. Artifact: `reports/team_strength_backtest.json`. Next levers, in order:
recency-decay grid, per-era team-name normalization to recover pre-2019 seasons, and
using these probabilities as an FPL fixture-strength challenger against ordinal
strength factors.

## Interval calibration (2026-08-24)

Diagnosis from the split-transition artifact: starter undercoverage is a global
upper-tail problem, not transition-specific. Starter coverage was 0.715 (2025/26) and
0.747 (2024/25) with 20-25% of actuals above the upper bound versus only ~3% below,
while all-player coverage stayed healthy because zeros dominate. Interval width was
nearly uniform (~5.0) across cohorts, i.e. variance-dominated.

Challenger: multiply only the distance from expected points to the upper bound.
Means, ordering, minutes, lower bounds and reported risk are bit-invariant by
construction (`src/fplengine/transition_uncertainty.py`). Grid over global upper
factors {1.0, 1.25, 1.5, 2.0} x optional club-change extra {1.0, 1.5}.

Results (starter coverage / mean width / share above upper):

| Factor | 2025/26 | 2024/25 |
|---|---|---|
| 1.00 (baseline) | 0.715 / 5.03 / 24.5% | 0.747 / 5.12 / 20.4% |
| 1.50 | 0.793 / 6.39 / 17.4% | 0.820 / 6.50 / 13.0% |
| 2.00 | 0.857 / 7.74 / 11.0% | 0.869 / 7.87 / 8.2% |

NDCG@10 is identical across every candidate in both seasons (0.4268 / 0.4471). The
x2 factor lands closest to the ~0.85 two-sided target on both seasons; a targeted
club-change extra adds little because the miscoverage is global.

Status: validated challenger `xp-v0.3-interval-calibration` (artifacts
`reports/interval_calibration_2025_26.json`, `reports/interval_calibration_2024_25.json`).
Recommended follow-up: adopt as an uncertainty-only patch in the next production
version bump; it changes no ranking output. Not silently folded into xp-v0.2.0.

## Split transition role decay (PR #18, 2026-08-24)

Grid over club-change role-retention weight {0, 0.25, 0.5, 0.75, 1.0} x promoted-team
weight {0, 0.5, 1.0}, composed multiplicatively so both axes stay identifiable
(`reports/split_transition_2025_26.json`). Held-out target 2025/26 GW1-10; priors
role=1 / attack=3 / ancillary=3 seasons from the Vaastav archive commit `c2add96`.
No production model changed.

Pre-season cohorts: 479 same-club, 37 established transfers, 22 transfers into promoted
clubs, 62 new to FPL, 64 promoted-club signings with no FPL history, 26 returning
promoted-club veterans with no current role evidence.

Development-season results:

- Established transfers improve monotonically under decay in every phase:
  minutes MAE 24.25 -> 19.78 (-18%), points MAE 1.48 -> 1.27, minutes bias +6.09 ->
  -0.36, interval coverage 0.830 -> 0.865, within-cohort NDCG up.
- Transfers into promoted clubs prefer partial decay (minutes MAE optimum ~12-25%
  retention: 24.44 -> 22.34) but samples are small (220 player-GWs).
- Global starter NDCG@10 falls monotonically with decay (0.4268 -> 0.4110) and top-10
  actual returns drop 5.28 -> 5.02; starter points MAE is flat (~2.317).
- The earlier "promotion context is insensitive" reading was partly structural: most
  promoted-club players carry no historical role evidence at all, so no weight can
  affect them.

Directional replication on untouched 2024/25 (priors <= 2023/24, GW1-10): the
established-transfer mechanism replicates exactly (minutes MAE 18.84 -> 16.57,
points MAE 1.03 -> 0.89), but the *global* ranking effect flips sign (NDCG 0.440 ->
0.458 improved with decay). One season of ~37 transfers is too small for global
top-10 conclusions either way.

Decision: xp-v0.3.0 promotion REJECTED again. No grid point achieved a Pareto win on
the development season, and post-hoc use of the confirmation season would break the
dev/confirm split. Durable learning: old-club role evidence systematically overpredicts
transfer minutes (+6 bias) and this replicates across seasons while global ranking
effects do not. Next experiment: widen transfer uncertainty/risk without moving mean
xP, which can improve calibration coverage without reordering the top of the ranking.

## v0.2 evidence decision

The live 2026/27 bootstrap returned zero in every legacy attack/defence strength field.
v0.1 clamped those values to its minimum goal-rate path, erasing most team and opponent
differences. It also allowed ownership and price to stand in for role evidence and put
too much weight on a single match of xG, saves and defensive actions.

The accepted challenger uses stable-code prior-season role/rate aggregates, hierarchical
shrinkage and the still-populated ordinal team strengths. Previous-season team-xG priors
were tested but not promoted: they slightly improved starter MAE while reducing NDCG@10
from 0.396 to 0.386. Complexity that loses on the intended ranking metric stays out.

The public historical archive is research evidence, not proof that its archived FPL xP
was captured predeadline. Raw archives remain ignored; the repository contains only a
compact aggregate prior with source-file hashes.

## FPL 2026/27

- The official scoring table awards 10/6/5/4 points per goal by GK/DEF/MID/FWD,
  three per assist, four for GK/DEF clean sheets, one for MID clean sheets, save points,
  and the standard card/concession deductions. [Official scoring](https://www.premierleague.com/en/news/2174909)
- Defensive-contribution scoring remains: two points for 10 defender CBIT or 12
  midfielder/forward CBIRT, capped at two per match. [Official explanation](https://www.premierleague.com/en/news/4361991/)
- The 2026/27 BPS changed to reduce overlap with defensive contributions and improve
  prospects for goalkeepers, full-backs, and attackers. [Official BPS update](https://www.premierleague.com/en/news/4679946/whats-new-in-202627-fantasy-changes-to-bonus-points-system)
- Chips remain twice per season half and managers can roll up to five free transfers.
  [Official season changes](https://www.premierleague.com/en/news/4679873/all-you-need-to-know-about-changes-to-fpl-for-202627)
- The live bootstrap currently contains 609 players, 20 teams, and 38 events; the fixture
  endpoint contains 380 league fixtures. These counts are observed runtime facts, not
  permanent API guarantees.

## Modelling direction

Maher's attack/defence Poisson hierarchy remains the appropriate interpretable baseline
for team score distributions. [Maher (1982), DOI](https://doi.org/10.1111/j.1467-9574.1982.tb00782.x)
Dixon-Coles-type low-score correction and time decay are the next team-model step, but
they need historical match data and out-of-sample evaluation before inclusion.

Expected FPL points should be decomposed rather than directly regressed at first:
minutes, team goals, player goal/assist share, clean sheets, saves, defensive actions,
cards, and bonus have different mechanisms and uncertainty. This also makes rule changes
and error diagnosis tractable.

## Open data landscape

- [StatsBomb Open Data](https://github.com/statsbomb/open-data) is explicitly available
  for research/genuine interest with attribution and includes event/lineup/selected 360
  data, but it is not a complete live Premier League feed.
- [OpenFootball](https://github.com/openfootball/football.json) publishes CC0/public-domain
  match fixtures/results and is a clean future backfill source.
- [Vaastav's FPL history](https://github.com/vaastav/Fantasy-Premier-League) remains the
  most useful community catalog, but its own notice says weekly updates stopped after
  2024/25. It should seed a licensed, checksummed historical import—not become an
  unexamined live dependency.
- [football-data.co.uk](https://www.football-data.co.uk/data) offers long free results,
  match stats, and odds CSVs. It is a future team-model candidate after source terms and
  column stability are documented.

## Neon and GitHub

The live Neon project already exists, uses Postgres 18, has a 512 MB logical-size limit,
and held about 31.8 MB when inspected. Its only existing public table was an unrelated
80 KB `fpl_snapshots` table. The proposed isolated schema adds no raw-payload archive.

Neon's published Free plan allowance was increased to 100 CU-hours and 0.5 GB per
project. [Neon plan update](https://neon.com/docs/changelog/2025-09-19)

GitHub standard hosted runners are free for public repositories. GitHub Free private
repositories include 2,000 minutes/month and 500 MB artifact/package storage; larger
runners are always chargeable. [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

The proposed four short Linux runs per day should remain far below 2,000 minutes, but
the repository owner must still keep Actions paid usage disabled or capped at $0.
