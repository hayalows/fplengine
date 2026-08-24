"""Exact FPL squad, lineup, captain, and transfer optimisation.

The optimiser consumes versioned Prediction objects. It does not create projections and
therefore remains model-agnostic: v0.2, shadow challengers, and later calibrated models
can all be compared through the same decision layer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pulp

from .model import Prediction
from .rules import (
    INITIAL_BUDGET_TENTHS,
    LINEUP_MAXIMUMS,
    LINEUP_MINIMUMS,
    MAX_BANKED_FREE_TRANSFERS,
    MAX_PLAYERS_PER_CLUB,
    SQUAD_POSITION_QUOTAS,
    SQUAD_SIZE,
    STARTING_SIZE,
    RulePlayer,
    transfer_hit_cost,
    validate_squad,
)


@dataclass(frozen=True)
class PlannedPlayer:
    player_id: int
    name: str
    team: str
    team_id: int
    position: str
    price: float
    expected_points: float
    expected_minutes: float
    risk: float


@dataclass(frozen=True)
class EventLineup:
    event: int
    starters: tuple[PlannedPlayer, ...]
    captain: PlannedPlayer
    vice_captain: PlannedPlayer
    bench_goalkeeper: PlannedPlayer
    bench_outfield: tuple[PlannedPlayer, ...]
    starting_xp: float
    captain_xp: float
    projected_points: float


@dataclass(frozen=True)
class OptimizationResult:
    status: str
    model_version: str
    events: tuple[int, ...]
    squad: tuple[PlannedPlayer, ...]
    lineups: tuple[EventLineup, ...]
    squad_cost: float
    bank_after: float
    transfers_in: tuple[PlannedPlayer, ...]
    transfers_out: tuple[PlannedPlayer, ...]
    transfers_used: int
    free_transfers: int
    hit_cost: int
    weighted_projected_points: float
    objective_value: float
    assumptions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _price_tenths(price: float) -> int:
    return int(round(float(price) * 10))


def _prepare(
    predictions_by_event: dict[int, list[Prediction]],
) -> tuple[list[int], dict[int, Prediction], dict[int, dict[int, Prediction]]]:
    if not predictions_by_event:
        raise ValueError("at least one event's predictions are required")
    events = sorted(int(event) for event in predictions_by_event)
    event_maps: dict[int, dict[int, Prediction]] = {}
    metadata: dict[int, Prediction] = {}
    for event in events:
        rows = predictions_by_event[event]
        if not rows:
            raise ValueError(f"GW{event} prediction list is empty")
        event_maps[event] = {row.player_id: row for row in rows}
        for row in rows:
            existing = metadata.get(row.player_id)
            if existing is not None and (
                existing.position != row.position or existing.team_id != row.team_id
            ):
                raise ValueError(f"player {row.player_id} metadata changes within optimisation horizon")
            metadata[row.player_id] = row
    common = set.intersection(*(set(rows) for rows in event_maps.values()))
    if len(common) < SQUAD_SIZE:
        raise ValueError("too few players have projections in every target event")
    metadata = {player_id: metadata[player_id] for player_id in common}
    event_maps = {
        event: {player_id: rows[player_id] for player_id in common}
        for event, rows in event_maps.items()
    }
    return events, metadata, event_maps


def _planned(row: Prediction) -> PlannedPlayer:
    return PlannedPlayer(
        player_id=row.player_id,
        name=row.player_name,
        team=row.team,
        team_id=row.team_id,
        position=row.position,
        price=row.price,
        expected_points=row.expected_points,
        expected_minutes=row.expected_minutes,
        risk=row.risk,
    )


def _add_squad_and_lineup_constraints(
    problem: pulp.LpProblem,
    *,
    events: list[int],
    metadata: dict[int, Prediction],
    event_maps: dict[int, dict[int, Prediction]],
    budget_tenths: int | None,
) -> tuple[
    dict[int, pulp.LpVariable],
    dict[tuple[int, int], pulp.LpVariable],
    dict[tuple[int, int], pulp.LpVariable],
]:
    ids = sorted(metadata)
    squad = {player_id: pulp.LpVariable(f"squad_{player_id}", cat="Binary") for player_id in ids}
    starting = {
        (event, player_id): pulp.LpVariable(f"start_{event}_{player_id}", cat="Binary")
        for event in events
        for player_id in ids
    }
    captain = {
        (event, player_id): pulp.LpVariable(f"captain_{event}_{player_id}", cat="Binary")
        for event in events
        for player_id in ids
    }
    problem += pulp.lpSum(squad.values()) == SQUAD_SIZE
    for position, quota in SQUAD_POSITION_QUOTAS.items():
        problem += (
            pulp.lpSum(
                squad[player_id]
                for player_id in ids
                if metadata[player_id].position == position
            )
            == quota
        )
    club_ids = sorted({row.team_id for row in metadata.values()})
    for club_id in club_ids:
        problem += (
            pulp.lpSum(
                squad[player_id]
                for player_id in ids
                if metadata[player_id].team_id == club_id
            )
            <= MAX_PLAYERS_PER_CLUB
        )
    if budget_tenths is not None:
        problem += (
            pulp.lpSum(
                _price_tenths(metadata[player_id].price) * squad[player_id]
                for player_id in ids
            )
            <= int(budget_tenths)
        )

    for event in events:
        problem += pulp.lpSum(starting[event, player_id] for player_id in ids) == STARTING_SIZE
        problem += pulp.lpSum(captain[event, player_id] for player_id in ids) == 1
        for player_id in ids:
            problem += starting[event, player_id] <= squad[player_id]
            problem += captain[event, player_id] <= starting[event, player_id]
        for position, minimum in LINEUP_MINIMUMS.items():
            problem += (
                pulp.lpSum(
                    starting[event, player_id]
                    for player_id in ids
                    if event_maps[event][player_id].position == position
                )
                >= minimum
            )
        for position, maximum in LINEUP_MAXIMUMS.items():
            problem += (
                pulp.lpSum(
                    starting[event, player_id]
                    for player_id in ids
                    if event_maps[event][player_id].position == position
                )
                <= maximum
            )
    return squad, starting, captain


def _objective(
    *,
    events: list[int],
    ids: list[int],
    event_maps: dict[int, dict[int, Prediction]],
    squad: dict[int, pulp.LpVariable],
    starting: dict[tuple[int, int], pulp.LpVariable],
    captain: dict[tuple[int, int], pulp.LpVariable],
    event_weights: dict[int, float],
    bench_weight: float,
    risk_penalty: float,
) -> pulp.LpAffineExpression:
    terms: list[pulp.LpAffineExpression] = []
    for event in events:
        weight = float(event_weights.get(event, 1.0))
        for player_id in ids:
            row = event_maps[event][player_id]
            # Starting xP plus captain's extra copy. A small bench term values squad resilience.
            terms.append(weight * row.expected_points * starting[event, player_id])
            terms.append(weight * row.expected_points * captain[event, player_id])
            if bench_weight:
                terms.append(
                    weight
                    * bench_weight
                    * row.expected_points
                    * (squad[player_id] - starting[event, player_id])
                )
            if risk_penalty:
                terms.append(-weight * risk_penalty * row.risk * starting[event, player_id])
    return pulp.lpSum(terms)


def _solve(problem: pulp.LpProblem, time_limit_seconds: int) -> None:
    solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=max(1, int(time_limit_seconds)))
    problem.solve(solver)
    status = pulp.LpStatus.get(problem.status, str(problem.status))
    if status not in {"Optimal", "Integer Feasible"}:
        raise RuntimeError(f"optimizer did not find a usable solution: {status}")


def _extract(
    *,
    problem: pulp.LpProblem,
    events: list[int],
    metadata: dict[int, Prediction],
    event_maps: dict[int, dict[int, Prediction]],
    squad_vars: dict[int, pulp.LpVariable],
    starting_vars: dict[tuple[int, int], pulp.LpVariable],
    captain_vars: dict[tuple[int, int], pulp.LpVariable],
    event_weights: dict[int, float],
    bank_after_tenths: int,
    current_ids: set[int] | None = None,
    free_transfers: int = 0,
    hit_cost: int = 0,
    assumptions: tuple[str, ...] = (),
) -> OptimizationResult:
    chosen_ids = {player_id for player_id, variable in squad_vars.items() if variable.value() > 0.5}
    squad_rows = tuple(
        sorted(
            (_planned(metadata[player_id]) for player_id in chosen_ids),
            key=lambda row: (row.position, -row.expected_points, row.name),
        )
    )
    lineups: list[EventLineup] = []
    weighted_points = 0.0
    for event in events:
        starters = {
            player_id
            for player_id in chosen_ids
            if starting_vars[event, player_id].value() > 0.5
        }
        captain_id = next(
            player_id
            for player_id in starters
            if captain_vars[event, player_id].value() > 0.5
        )
        starter_rows = sorted(
            (_planned(event_maps[event][player_id]) for player_id in starters),
            key=lambda row: (-row.expected_points, row.position, row.name),
        )
        captain_row = _planned(event_maps[event][captain_id])
        vice_row = next(row for row in starter_rows if row.player_id != captain_id)
        bench_ids = chosen_ids - starters
        bench_gk_id = next(
            player_id for player_id in bench_ids if metadata[player_id].position == "GK"
        )
        bench_out_ids = [
            player_id for player_id in bench_ids if metadata[player_id].position != "GK"
        ]
        bench_out_rows = tuple(
            sorted(
                (_planned(event_maps[event][player_id]) for player_id in bench_out_ids),
                key=lambda row: (-row.expected_points, row.risk, row.name),
            )
        )
        starting_xp = sum(row.expected_points for row in starter_rows)
        projected = starting_xp + captain_row.expected_points
        weighted_points += float(event_weights.get(event, 1.0)) * projected
        lineups.append(
            EventLineup(
                event=event,
                starters=tuple(starter_rows),
                captain=captain_row,
                vice_captain=vice_row,
                bench_goalkeeper=_planned(event_maps[event][bench_gk_id]),
                bench_outfield=bench_out_rows,
                starting_xp=round(starting_xp, 3),
                captain_xp=round(captain_row.expected_points, 3),
                projected_points=round(projected, 3),
            )
        )

    current = current_ids or set()
    transfers_in = tuple(
        sorted(
            (_planned(metadata[player_id]) for player_id in chosen_ids - current),
            key=lambda row: (-row.expected_points, row.name),
        )
    ) if current_ids is not None else ()
    transfers_out = tuple(
        sorted(
            (_planned(metadata[player_id]) for player_id in current - chosen_ids),
            key=lambda row: (row.expected_points, row.name),
        )
    ) if current_ids is not None else ()
    model_versions = {event_maps[event][next(iter(chosen_ids))].model_version for event in events}
    model_version = "+".join(sorted(model_versions))
    return OptimizationResult(
        status=pulp.LpStatus.get(problem.status, str(problem.status)),
        model_version=model_version,
        events=tuple(events),
        squad=squad_rows,
        lineups=tuple(lineups),
        squad_cost=round(sum(metadata[player_id].price for player_id in chosen_ids), 1),
        bank_after=round(bank_after_tenths / 10.0, 1),
        transfers_in=transfers_in,
        transfers_out=transfers_out,
        transfers_used=len(transfers_in),
        free_transfers=int(free_transfers),
        hit_cost=int(hit_cost),
        weighted_projected_points=round(weighted_points - hit_cost, 3),
        objective_value=round(float(pulp.value(problem.objective)), 4),
        assumptions=assumptions,
    )


def optimize_static_squad(
    predictions_by_event: dict[int, list[Prediction]],
    *,
    budget: float = 100.0,
    event_weights: dict[int, float] | None = None,
    bench_weight: float = 0.08,
    risk_penalty: float = 0.0,
    time_limit_seconds: int = 15,
) -> OptimizationResult:
    """Choose one legal 15-player squad and optimal XI/captain for every target event."""
    events, metadata, event_maps = _prepare(predictions_by_event)
    weights = event_weights or {event: 1.0 for event in events}
    problem = pulp.LpProblem("fpl_static_squad", pulp.LpMaximize)
    squad, starting, captain = _add_squad_and_lineup_constraints(
        problem,
        events=events,
        metadata=metadata,
        event_maps=event_maps,
        budget_tenths=_price_tenths(budget),
    )
    ids = sorted(metadata)
    problem += _objective(
        events=events,
        ids=ids,
        event_maps=event_maps,
        squad=squad,
        starting=starting,
        captain=captain,
        event_weights=weights,
        bench_weight=bench_weight,
        risk_penalty=risk_penalty,
    )
    _solve(problem, time_limit_seconds)
    result = _extract(
        problem=problem,
        events=events,
        metadata=metadata,
        event_maps=event_maps,
        squad_vars=squad,
        starting_vars=starting,
        captain_vars=captain,
        event_weights=weights,
        bank_after_tenths=_price_tenths(budget)
        - sum(
            _price_tenths(metadata[player_id].price)
            for player_id, variable in squad.items()
            if variable.value() > 0.5
        ),
        assumptions=(
            "Exact mixed-integer optimisation under 2026/27 squad, formation, budget, and club limits.",
            "Future player prices are held at the current observed price across the horizon.",
            "Bench weight is a resilience/tie-break preference and is not counted as ordinary FPL points.",
        ),
    )
    validate_squad(
        [
            RulePlayer(row.player_id, row.position, row.team_id, _price_tenths(row.price))
            for row in result.squad
        ],
        _price_tenths(budget),
    )
    return result


def optimize_transfers(
    current_player_ids: set[int] | list[int] | tuple[int, ...],
    predictions_by_event: dict[int, list[Prediction]],
    *,
    bank: float,
    free_transfers: int,
    selling_prices: dict[int, float] | None = None,
    max_transfers: int = 3,
    event_weights: dict[int, float] | None = None,
    bench_weight: float = 0.08,
    risk_penalty: float = 0.0,
    time_limit_seconds: int = 15,
) -> OptimizationResult:
    """Choose the best legal transfer set now, evaluated over one or more future GWs."""
    if not 1 <= int(free_transfers) <= MAX_BANKED_FREE_TRANSFERS:
        raise ValueError("free_transfers must be between 1 and 5")
    if max_transfers < 0:
        raise ValueError("max_transfers cannot be negative")
    events, metadata, event_maps = _prepare(predictions_by_event)
    current = {int(player_id) for player_id in current_player_ids}
    if len(current) != SQUAD_SIZE:
        raise ValueError("current squad must contain exactly 15 player IDs")
    missing = current.difference(metadata)
    if missing:
        raise ValueError(f"current squad players missing from projections: {sorted(missing)}")
    current_rules = [
        RulePlayer(
            player_id,
            metadata[player_id].position,
            metadata[player_id].team_id,
            _price_tenths(metadata[player_id].price),
        )
        for player_id in current
    ]
    # Do not apply a current-price budget cap: existing squad value can exceed £100m.
    validate_squad(current_rules)
    weights = event_weights or {event: 1.0 for event in events}
    prices = selling_prices or {}
    selling_tenths = {
        player_id: _price_tenths(prices.get(player_id, metadata[player_id].price))
        for player_id in current
    }
    bank_tenths = _price_tenths(bank)

    problem = pulp.LpProblem("fpl_transfer_plan", pulp.LpMaximize)
    squad, starting, captain = _add_squad_and_lineup_constraints(
        problem,
        events=events,
        metadata=metadata,
        event_maps=event_maps,
        budget_tenths=None,
    )
    ids = sorted(metadata)
    transfer_in = {
        player_id: squad[player_id]
        for player_id in ids
        if player_id not in current
    }
    transfer_out = {
        player_id: 1 - squad[player_id]
        for player_id in current
    }
    transfer_count = pulp.lpSum(transfer_in.values())
    problem += transfer_count <= int(max_transfers)
    problem += transfer_count == pulp.lpSum(transfer_out.values())
    purchase_cost = pulp.lpSum(
        _price_tenths(metadata[player_id].price) * variable
        for player_id, variable in transfer_in.items()
    )
    sale_value = pulp.lpSum(
        selling_tenths[player_id] * variable
        for player_id, variable in transfer_out.items()
    )
    problem += purchase_cost <= bank_tenths + sale_value

    paid_transfers = pulp.LpVariable("paid_transfers", lowBound=0, cat="Integer")
    problem += paid_transfers >= transfer_count - int(free_transfers)
    base_objective = _objective(
        events=events,
        ids=ids,
        event_maps=event_maps,
        squad=squad,
        starting=starting,
        captain=captain,
        event_weights=weights,
        bench_weight=bench_weight,
        risk_penalty=risk_penalty,
    )
    problem += base_objective - 4.0 * paid_transfers
    _solve(problem, time_limit_seconds)

    chosen = {player_id for player_id, variable in squad.items() if variable.value() > 0.5}
    actual_in = chosen - current
    actual_out = current - chosen
    actual_hit = transfer_hit_cost(len(actual_in), int(free_transfers))
    bank_after = bank_tenths + sum(selling_tenths[player_id] for player_id in actual_out) - sum(
        _price_tenths(metadata[player_id].price) for player_id in actual_in
    )
    return _extract(
        problem=problem,
        events=events,
        metadata=metadata,
        event_maps=event_maps,
        squad_vars=squad,
        starting_vars=starting,
        captain_vars=captain,
        event_weights=weights,
        bank_after_tenths=bank_after,
        current_ids=current,
        free_transfers=int(free_transfers),
        hit_cost=actual_hit,
        assumptions=(
            "Transfers are made now and the resulting squad is held across the supplied projection horizon.",
            "Paid transfers cost four FPL points each beyond the supplied banked free transfers.",
            "Exact selling prices are used when supplied; otherwise current purchase prices are a documented approximation.",
            "The option value of saving a free transfer for a later Gameweek is not yet modelled dynamically.",
            "Future price changes and chip use are not forecast in this optimisation pass.",
        ),
    )
