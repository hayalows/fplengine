"""Held-out benchmark for component-specific historical memory."""

from __future__ import annotations

from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .benchmark import SeasonArchive
from .component_history import component_window_variants
from .historical import build_season_evidence
from .history_benchmark import benchmark_history_candidate, benchmark_simple_baselines


def run_component_history_experiment(
    data_root: Path,
    *,
    target_season: str,
    prior_seasons: Iterable[str],
    role_windows: tuple[int, ...] = (1, 2, 3),
    attack_windows: tuple[int, ...] = (1, 2, 3),
    ancillary_windows: tuple[int, ...] = (1, 3, 5, 9),
    decay: float = 1.0,
    first_event: int = 6,
    last_event: int = 38,
) -> dict[str, Any]:
    prior_names = list(prior_seasons)
    target_start = int(target_season.split("-", 1)[0])
    invalid = [name for name in prior_names if int(name.split("-", 1)[0]) >= target_start]
    if invalid:
        raise ValueError(f"Prior seasons must precede {target_season}: {invalid}")

    evidence = [build_season_evidence(data_root / season, season) for season in prior_names]
    variants = component_window_variants(
        evidence,
        role_windows=role_windows,
        attack_windows=attack_windows,
        ancillary_windows=ancillary_windows,
        decay=decay,
    )
    archive = SeasonArchive(data_root / target_season)
    candidates: dict[str, Any] = {}
    for label, priors in variants.items():
        result = benchmark_history_candidate(
            archive,
            priors,
            first_event=first_event,
            last_event=last_event,
            label=label,
        )
        result["component_sources"] = priors.get("component_sources", {})
        candidates[label] = result

    def ranking_key(item: tuple[str, dict[str, Any]]) -> tuple[float, float, float]:
        starter = item[1]["metrics"]["starters"]
        return (
            starter.get("ndcg_at_10", 0.0),
            starter.get("top10_actual_mean", 0.0),
            -starter.get("mae", 999.0),
        )

    leaderboard = []
    for label, result in sorted(candidates.items(), key=ranking_key, reverse=True):
        starter = result["metrics"]["starters"]
        all_players = result["metrics"]["all"]
        sources = result.get("component_sources", {})
        leaderboard.append(
            {
                "label": label,
                "role_seasons": len(sources.get("role", {}).get("seasons", [])),
                "attack_seasons": len(sources.get("attack", {}).get("seasons", [])),
                "ancillary_seasons": len(sources.get("ancillary", {}).get("seasons", [])),
                "starter_mae": starter.get("mae"),
                "starter_ndcg_at_10": starter.get("ndcg_at_10"),
                "starter_top10_actual_mean": starter.get("top10_actual_mean"),
                "starter_spearman": starter.get("spearman"),
                "all_mae": all_players.get("mae"),
                "all_ndcg_at_10": all_players.get("ndcg_at_10"),
            }
        )

    # Marginal summaries help distinguish a real component effect from a lucky single
    # combination. Average every candidate sharing the same window for that component.
    marginals: dict[str, dict[str, dict[str, float]]] = {}
    for component in ("role", "attack", "ancillary"):
        grouped: dict[int, list[dict[str, float]]] = {}
        for row in leaderboard:
            window = int(row[f"{component}_seasons"])
            grouped.setdefault(window, []).append(row)
        marginals[component] = {
            str(window): {
                "mean_starter_ndcg_at_10": round(
                    mean(row["starter_ndcg_at_10"] for row in rows), 6
                ),
                "mean_starter_mae": round(mean(row["starter_mae"] for row in rows), 6),
                "mean_top10_actual": round(
                    mean(row["starter_top10_actual_mean"] for row in rows), 6
                ),
            }
            for window, rows in sorted(grouped.items())
        }

    return {
        "experiment": "component-specific-history-depth-v0.3",
        "target_season": target_season,
        "prior_seasons_available": prior_names,
        "first_event": first_event,
        "last_event": last_event,
        "decay": decay,
        "simple_baselines": benchmark_simple_baselines(
            archive, first_event=first_event, last_event=last_event
        ),
        "marginals": marginals,
        "leaderboard": leaderboard,
        "candidates": candidates,
    }
