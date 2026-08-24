"""2026/27 Fantasy Premier League squad and transfer rules used by optimizers.

The rules in this module are game constraints, not modelling assumptions. Keep them
separate from expected-points logic so a rules change cannot silently alter forecasts.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

SQUAD_SIZE = 15
STARTING_SIZE = 11
INITIAL_BUDGET_TENTHS = 1000
MAX_PLAYERS_PER_CLUB = 3
MAX_BANKED_FREE_TRANSFERS = 5
TRANSFER_HIT_POINTS = 4
SQUAD_POSITION_QUOTAS = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
LINEUP_MINIMUMS = {"GK": 1, "DEF": 3, "MID": 2, "FWD": 1}
LINEUP_MAXIMUMS = {"GK": 1, "DEF": 5, "MID": 5, "FWD": 3}


@dataclass(frozen=True)
class RulePlayer:
    player_id: int
    position: str
    team_id: int
    price_tenths: int


def selling_price_tenths(purchase_price_tenths: int, current_price_tenths: int) -> int:
    """Return FPL selling value: half of profit, rounded down; all losses are realized."""
    purchase = int(purchase_price_tenths)
    current = int(current_price_tenths)
    if purchase <= 0 or current <= 0:
        raise ValueError("prices must be positive")
    if current <= purchase:
        return current
    return purchase + (current - purchase) // 2


def transfer_hit_cost(transfers_used: int, free_transfers: int) -> int:
    if transfers_used < 0:
        raise ValueError("transfers_used cannot be negative")
    if not 1 <= free_transfers <= MAX_BANKED_FREE_TRANSFERS:
        raise ValueError("free_transfers must be between 1 and 5")
    return max(0, int(transfers_used) - int(free_transfers)) * TRANSFER_HIT_POINTS


def next_free_transfers(free_transfers: int, transfers_used: int) -> int:
    """Free transfers available next GW without a chip-specific exception."""
    if not 1 <= free_transfers <= MAX_BANKED_FREE_TRANSFERS:
        raise ValueError("free_transfers must be between 1 and 5")
    if transfers_used < 0:
        raise ValueError("transfers_used cannot be negative")
    remaining = max(0, int(free_transfers) - int(transfers_used))
    return min(MAX_BANKED_FREE_TRANSFERS, remaining + 1)


def validate_squad(players: Iterable[RulePlayer], budget_tenths: int | None = None) -> None:
    rows = list(players)
    if len(rows) != SQUAD_SIZE:
        raise ValueError(f"squad must contain exactly {SQUAD_SIZE} players")
    ids = [row.player_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("squad contains duplicate players")
    positions = Counter(row.position for row in rows)
    if positions != Counter(SQUAD_POSITION_QUOTAS):
        raise ValueError(
            f"squad positions must be {SQUAD_POSITION_QUOTAS}; observed {dict(positions)}"
        )
    clubs = Counter(row.team_id for row in rows)
    if max(clubs.values(), default=0) > MAX_PLAYERS_PER_CLUB:
        raise ValueError("squad exceeds the maximum of three players from one club")
    if budget_tenths is not None:
        total = sum(row.price_tenths for row in rows)
        if total > int(budget_tenths):
            raise ValueError(f"squad costs {total / 10:.1f} but budget is {budget_tenths / 10:.1f}")


def validate_lineup(players: Iterable[RulePlayer]) -> None:
    rows = list(players)
    if len(rows) != STARTING_SIZE:
        raise ValueError(f"starting lineup must contain exactly {STARTING_SIZE} players")
    positions = Counter(row.position for row in rows)
    for position, minimum in LINEUP_MINIMUMS.items():
        if positions[position] < minimum:
            raise ValueError(f"lineup needs at least {minimum} {position}")
    for position, maximum in LINEUP_MAXIMUMS.items():
        if positions[position] > maximum:
            raise ValueError(f"lineup may contain at most {maximum} {position}")
