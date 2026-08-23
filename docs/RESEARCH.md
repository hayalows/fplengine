# Research findings

Research was refreshed on 2026-08-23 and favored primary/official sources.

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
