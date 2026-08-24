# Decision optimizer

The optimizer is deliberately separate from the expected-points model. Forecasts answer
"what do we think will happen?"; the optimizer answers "given those forecasts and the
FPL rules, what legal decision maximizes the chosen objective?"

## 2026/27 rules encoded

The implementation is grounded in the current official Premier League/FPL help material:

- https://www.premierleague.com/en/news/2174419/1000
- https://www.premierleague.com/en/news/2174899/fpl-basics-managing-your-team
- https://www.premierleague.com/en/news/2174907/fpl-basics-explained-how-to-make-transfers
- https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627

Current constraints used by the solver:

- 15-player squad and £100.0m initial budget;
- 2 GK, 5 DEF, 5 MID, 3 FWD;
- no more than 3 players from one club;
- starting XI has exactly 1 GK, at least 3 DEF, at least 2 MID, and at least 1 FWD;
- captain receives one extra copy of his projected points in normal Gameweeks;
- one free transfer is added each Gameweek and up to five can be banked;
- transfers beyond the supplied free-transfer balance cost 4 points each;
- on a profitable player sale, half the price rise is retained, rounded down to £0.1m;
- if a player's price falls below the purchase price, the full loss is realized.

Chip rules are documented but are not yet decision variables in the first optimizer release.
2026/27 again has two sets of Wildcard, Free Hit, Triple Captain and Bench Boost, with
only one chip usable in a Gameweek.

## Exact static-squad optimization

`fplopt squad` uses mixed-integer optimization to select a legal 15-player squad. For
each Gameweek in the supplied horizon it also chooses the legal XI and captain. The
objective is the weighted sum of projected XI points plus the captain's extra projected
points. A small configurable bench weight can prefer a more resilient squad without
pretending ordinary bench points count in the Gameweek score.

Example:

```bash
fplopt squad --horizon 5 --decay 0.9
```

This is useful for initial-squad construction, Wildcard research, and finding the best
static squad structure over a fixture run.

## Exact transfer optimization

`fplopt manager ENTRY_ID --free-transfers N` starts from the latest public squad and
solves for the best legal set of transfers now, evaluated across the requested horizon.
It enforces positions, club limits, cash and transfer hits, then selects the optimal XI
and captain in every projected Gameweek.

Example:

```bash
fplopt manager 123456 --free-transfers 2 --horizon 4 --max-transfers 3
```

## Important limitations

The public picks endpoint does not reliably expose every owned player's exact current
selling price. The manager command therefore uses current purchase price as an explicit
approximation unless an exact selling-price source is supplied by a future authenticated
integration. The engine must not present an approximate budget-feasible plan as exact.

The first transfer optimizer chooses transfers at the current deadline and values the
resulting squad over a future horizon. It does **not** yet solve a sequence of different
transfer decisions at every future deadline, so it does not fully value the option to
bank a free transfer today.

Future prices are held at their current observed values. Price-change forecasting should
be added as a separate probabilistic layer rather than smuggled into the rules engine.

Wildcard, Free Hit, Bench Boost and Triple Captain are not yet optimization variables.
They should be added only with explicit half-season availability state and one-chip-per-GW
constraints.

## Evidence policy

An optimizer result is not evidence that the underlying forecast is correct. Every output
must preserve the projection model version and as-of timestamp. Future backtests should
compare decision policies, not only xP errors, including transfer regret, captain regret,
hit cost, chip timing, and full-season points.
