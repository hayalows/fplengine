# Research findings

Research was refreshed on 2026-08-23 and favored primary/official sources.

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
