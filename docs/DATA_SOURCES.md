# Data-source decisions

## Selected now

| Source | Role | Classification | Why selected | Safeguard |
|---|---|---|---|---|
| Official FPL public endpoints | live players, teams, fixtures, actuals, public managers | observed and FPL-calculated | current, free, stable IDs, direct FPL scoring fields | low request volume, retries, source hash, no authentication bypass |
| Existing Neon `fpl-lab` project | persistent production store | infrastructure | already provisioned, 512 MB project limit observed, no new project required | separate `engine` schema; compact normalized rows |
| GitHub Actions | scheduler and CI | infrastructure | $0 for public standard runners; bounded private-plan allowance | four runs/day, no artifacts, concurrency lock, secret-gated no-op |
| Local SQLite | development/test cache only | infrastructure | exact end-to-end testing without credentials | never described as production system of record |

The FPL endpoints are public but not a formally documented public developer API. That
means availability and fields may change. The adapter isolates schema drift and the
project must remain conservative about request volume.

## Candidates for controlled import

| Source | Potential value | Decision |
|---|---|---|
| Vaastav FPL historical dataset | player/gameweek history and stable FPL codes | valuable research candidate; weekly updates stopped after 2024/25 and redistribution/license terms require a dedicated review before automated ingestion |
| OpenFootball England/football.json | CC0 fixtures and results | accepted as a future independent results backfill; insufficient alone for FPL player modelling |
| StatsBomb Open Data | event-model research and xG methodology | accepted for research/training experiments where competitions overlap; not a current live Premier League feed |
| football-data.co.uk | long match-result/stat/odds history | potentially useful for team models; defer until terms, attribution, columns, and update reliability are pinned |
| Official player `element-summary` | past FPL seasons per current player | safe targeted enrichment | do not fetch all 609 players on every scheduled run; create a slow cached backfill job |

## Rejected for v0.1

| Source/approach | Reason |
|---|---|
| Understat scraping | no official free API and automation terms were not sufficiently clear for a default production dependency |
| FBref scraping | brittle page scraping and access restrictions make it unsuitable as a core scheduled source |
| news-site scraping | terms, copyright, entity resolution, and false-positive risk; official FPL news is safer for the baseline |
| paid Opta/StatsBomb feeds | violates the recurring $0 constraint |
| paid AI extraction | unnecessary for engine function and violates the no-paid-AI requirement |
| bookmaker API dependency | unstable free access and a poor zero-cost foundation; can be an optional challenger later |
| copying another FPL project wholesale | hides provenance and leakage assumptions; only methods and source catalogs should be studied |

## Stable identity policy

Primary identity is the season's FPL player ID. `fpl_code` and `opta_code` are stored as
cross-season/source mapping keys where supplied. Names are presentation fields and must
never be used as join keys. Any new source needs an explicit mapping table with match
method, confidence, reviewer state, and effective dates.

## Provenance policy

Every imported dataset must register:

- source and exact endpoint/file/version;
- retrieval timestamp and content hash;
- license/terms and attribution requirement;
- observed vs calculated fields;
- time at which the value became knowable;
- entity-mapping method and confidence.
