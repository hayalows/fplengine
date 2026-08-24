"""Compose historical priors with different memory depths per model component."""

from __future__ import annotations

from typing import Any, Iterable

from .historical import merge_season_evidence

ROLE_PLAYER_FIELDS = (
    "starts",
    "starts_opportunities",
    "starter_minutes",
    "substitute_appearances",
    "substitute_minutes",
)
ATTACK_PLAYER_FIELDS = (
    "expected_goals",
    "expected_goals_minutes",
    "expected_assists",
    "expected_assists_minutes",
)
ANCILLARY_PLAYER_FIELDS = (
    "saves",
    "saves_minutes",
    "bonus",
    "bonus_minutes",
    "yellow_cards",
    "yellow_cards_minutes",
    "red_cards",
    "red_cards_minutes",
)
DC_PLAYER_FIELDS = (
    "defensive_contribution",
    "defensive_contribution_minutes",
)
ROLE_POSITION_FIELDS = ("start_rate", "starter_minutes", "cameo_rate", "cameo_minutes")
ATTACK_POSITION_FIELDS = ("xg90", "xa90")
ANCILLARY_POSITION_FIELDS = ("saves90", "bonus90", "yellow90", "red90")
DC_POSITION_FIELDS = ("dc90",)


def _copy_player_fields(
    target_players: dict[str, dict[str, Any]],
    source_players: dict[str, dict[str, Any]],
    fields: tuple[str, ...],
) -> None:
    for code, source in source_players.items():
        target = target_players.setdefault(
            code,
            {
                "position": source.get("position") or "",
                "team": source.get("team") or "",
            },
        )
        for field in fields:
            if field in source:
                target[field] = source[field]


def _copy_position_fields(
    target_positions: dict[str, dict[str, float]],
    source_positions: dict[str, dict[str, float]],
    fields: tuple[str, ...],
) -> None:
    for position, source in source_positions.items():
        target = target_positions.setdefault(position, {})
        for field in fields:
            if field in source:
                target[field] = source[field]


def component_history_prior(
    payloads: Iterable[dict[str, Any]],
    *,
    role_window: int = 1,
    attack_window: int = 1,
    ancillary_window: int = 1,
    dc_window: int = 1,
    role_decay: float = 1.0,
    attack_decay: float = 1.0,
    ancillary_decay: float = 1.0,
    dc_decay: float = 1.0,
) -> dict[str, Any]:
    """Build a prior where model components can remember different seasons.

    Identity/team/position presentation comes from the most recent completed season.
    Each statistical family is then replaced by evidence from its own window. This is a
    challenger construction only; it never mutates the live v0.2 prior file.
    """
    materialized = list(payloads)
    if not materialized:
        return {
            "schema_version": 3,
            "season": None,
            "source_seasons": [],
            "component_sources": {},
            "league": {},
            "teams": {},
            "positions": {},
            "players": {},
        }

    base = merge_season_evidence(materialized, max_seasons=1, decay=1.0)
    role = merge_season_evidence(materialized, max_seasons=role_window, decay=role_decay)
    attack = merge_season_evidence(
        materialized, max_seasons=attack_window, decay=attack_decay
    )
    ancillary = merge_season_evidence(
        materialized, max_seasons=ancillary_window, decay=ancillary_decay
    )
    dc = merge_season_evidence(materialized, max_seasons=dc_window, decay=dc_decay)

    players: dict[str, dict[str, Any]] = {
        code: {
            "position": state.get("position") or "",
            "team": state.get("team") or "",
            "games": state.get("games", 0.0),
            "minutes": state.get("minutes", 0.0),
            "total_points": state.get("total_points", 0.0),
            "opportunities": state.get("opportunities", 0.0),
        }
        for code, state in base.get("players", {}).items()
    }
    # Players absent in the latest season may still be present in a wider historical
    # window. They are harmless for a target snapshot unless their stable FPL code
    # reappears, so preserve them as prior evidence.
    _copy_player_fields(players, role.get("players", {}), ROLE_PLAYER_FIELDS)
    _copy_player_fields(players, attack.get("players", {}), ATTACK_PLAYER_FIELDS)
    _copy_player_fields(players, ancillary.get("players", {}), ANCILLARY_PLAYER_FIELDS)
    _copy_player_fields(players, dc.get("players", {}), DC_PLAYER_FIELDS)

    positions: dict[str, dict[str, float]] = {}
    _copy_position_fields(positions, role.get("positions", {}), ROLE_POSITION_FIELDS)
    _copy_position_fields(positions, attack.get("positions", {}), ATTACK_POSITION_FIELDS)
    _copy_position_fields(
        positions, ancillary.get("positions", {}), ANCILLARY_POSITION_FIELDS
    )
    _copy_position_fields(positions, dc.get("positions", {}), DC_POSITION_FIELDS)

    component_sources = {
        "role": {
            "seasons": role.get("source_seasons", []),
            "decay": role_decay,
        },
        "attack": {
            "seasons": attack.get("source_seasons", []),
            "decay": attack_decay,
        },
        "ancillary": {
            "seasons": ancillary.get("source_seasons", []),
            "decay": ancillary_decay,
        },
        "defensive_contribution": {
            "seasons": dc.get("source_seasons", []),
            "decay": dc_decay,
        },
    }
    union_seasons = []
    for component in component_sources.values():
        for season in component["seasons"]:
            if season not in union_seasons:
                union_seasons.append(season)

    return {
        "schema_version": 3,
        "season": base.get("season"),
        "source_seasons": union_seasons,
        "component_sources": component_sources,
        "league": {},
        "teams": {},
        "positions": positions,
        "players": dict(sorted(players.items())),
    }


def component_window_variants(
    payloads: Iterable[dict[str, Any]],
    *,
    role_windows: tuple[int, ...] = (1, 2, 3),
    attack_windows: tuple[int, ...] = (1, 2, 3),
    ancillary_windows: tuple[int, ...] = (1, 3, 5, 9),
    decay: float = 1.0,
) -> dict[str, dict[str, Any]]:
    """Generate a focused grid to learn which components benefit from long memory."""
    materialized = list(payloads)
    result: dict[str, dict[str, Any]] = {}
    for role_window in role_windows:
        for attack_window in attack_windows:
            for ancillary_window in ancillary_windows:
                label = (
                    f"role{role_window}_attack{attack_window}_"
                    f"ancillary{ancillary_window}_decay{decay:.2f}"
                )
                result[label] = component_history_prior(
                    materialized,
                    role_window=role_window,
                    attack_window=attack_window,
                    ancillary_window=ancillary_window,
                    dc_window=1,
                    role_decay=decay,
                    attack_decay=decay,
                    ancillary_decay=decay,
                    dc_decay=decay,
                )
    return result
