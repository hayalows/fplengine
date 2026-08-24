"""Premier League team-strength and match-probability model.

A standalone Maher-style Poisson module: per-team attack/defence coefficients plus a
home-advantage term, optionally with a Dixon-Coles low-score correction. It is
intentionally separate from the FPL player model so it can power fixture projections,
captaincy ceilings, and general PL analysis without coupling to any model version.

Fitting is closed-form coordinate ascent on the weighted Poisson likelihood (no
third-party dependencies), and evaluation is walk-forward by match time so no target
match ever contributes to its own fit.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

MAX_GOALS = 10
_RHO_GRID = (-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15)


@dataclass(frozen=True)
class Match:
    home: str
    away: str
    home_goals: int
    away_goals: int
    kickoff: str = ""
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.home == self.away:
            raise ValueError("home and away team must differ")
        if self.home_goals < 0 or self.away_goals < 0:
            raise ValueError("goals cannot be negative")
        if self.weight < 0:
            raise ValueError("weight cannot be negative")


@dataclass(frozen=True)
class TeamRatings:
    attack: dict[str, float]
    defence: dict[str, float]
    home_advantage: float
    rho: float | None
    fitted_matches: int
    iterations: int
    log_likelihood: float
    source_note: str = "fit from completed match results; provenance recorded by caller"

    def lambda_home(self, home: str, away: str) -> float:
        return math.exp(self.home_advantage + self.attack[home] + self.defence[away])

    def lambda_away(self, home: str, away: str) -> float:
        return math.exp(self.attack[away] + self.defence[home])


@dataclass(frozen=True)
class MatchPrediction:
    home: str
    away: str
    expected_home_goals: float
    expected_away_goals: float
    home_win: float
    draw: float
    away_win: float
    most_likely_scores: tuple[tuple[str, float], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "home": self.home,
            "away": self.away,
            "expected_home_goals": round(self.expected_home_goals, 4),
            "expected_away_goals": round(self.expected_away_goals, 4),
            "probabilities": {
                "home_win": round(self.home_win, 6),
                "draw": round(self.draw, 6),
                "away_win": round(self.away_win, 6),
            },
            "most_likely_scores": [
                {"score": score, "probability": round(probability, 6)}
                for score, probability in self.most_likely_scores
            ],
        }


def _tau(home_goals: int, away_goals: int, lam_home: float, lam_away: float, rho: float) -> float:
    """Dixon-Coles low-score dependency correction."""
    if home_goals == 0 and away_goals == 0:
        return 1.0 - lam_home * lam_away * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + lam_home * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + lam_away * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


def _weighted_totals(matches: Sequence[Match]) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
    scored: dict[str, float] = defaultdict(float)
    conceded: dict[str, float] = defaultdict(float)
    played: dict[str, int] = defaultdict(int)
    for match in matches:
        scored[match.home] += match.weight * match.home_goals
        scored[match.away] += match.weight * match.away_goals
        conceded[match.home] += match.weight * match.away_goals
        conceded[match.away] += match.weight * match.home_goals
        played[match.home] += 1
        played[match.away] += 1
    return scored, conceded, played


def fit_team_ratings(
    matches: Sequence[Match],
    *,
    dixon_coles: bool = False,
    max_iterations: int = 400,
    tolerance: float = 1e-10,
) -> TeamRatings:
    """Fit attack/defence/home-advantage by coordinate ascent on the Poisson likelihood.

    Weights allow recency decay upstream. Attack is mean-centred each sweep for
    identifiability against the home-advantage term.
    """
    if len(matches) < 2:
        raise ValueError("at least two matches are required")
    teams = sorted({match.home for match in matches} | {match.away for match in matches})
    scored, conceded, played = _weighted_totals(matches)
    # A team with no completed weighted minutes is unidentifiable; zero goals in a
    # tiny window is legitimate evidence and is handled by epsilon smoothing below.
    for team in teams:
        if not played[team]:
            raise ValueError(f"team {team} has no matches; cannot identify ratings")
    attack = {team: 0.0 for team in teams}
    defence = {team: 0.0 for team in teams}
    total_home = sum(match.weight * match.home_goals for match in matches)
    total_away = sum(match.weight * match.away_goals for match in matches)
    home_advantage = math.log((total_home + 1e-12) / (total_away + 1e-12))

    home_matches_by_team: dict[str, list[Match]] = defaultdict(list)
    away_matches_by_team: dict[str, list[Match]] = defaultdict(list)
    for match in matches:
        home_matches_by_team[match.home].append(match)
        away_matches_by_team[match.away].append(match)

    previous = -math.inf
    log_likelihood = -math.inf
    iteration = 0
    for iteration in range(1, max_iterations + 1):
        for team in teams:
            exposure = sum(
                match.weight * math.exp(defence[match.away])
                for match in home_matches_by_team[team]
            ) + sum(
                # Playing away, our scoring rate faces the opponent's defence.
                match.weight * math.exp(defence[match.home])
                for match in away_matches_by_team[team]
            )
            attack[team] = math.log(scored[team] + 1e-9) - math.log(exposure + 1e-12)
        mean_attack = sum(attack.values()) / len(teams)
        for team in teams:
            attack[team] -= mean_attack
        for team in teams:
            exposure = sum(
                match.weight * math.exp(attack[match.away])
                for match in home_matches_by_team[team]
            ) + sum(
                match.weight * math.exp(attack[match.home])
                for match in away_matches_by_team[team]
            )
            defence[team] = math.log(conceded[team] + 1e-9) - math.log(exposure + 1e-12)
        home_exposure = sum(
            match.weight * math.exp(attack[match.home] + defence[match.away])
            for match in matches
        )
        home_advantage = math.log(total_home) - math.log(home_exposure)

        log_likelihood = 0.0
        for match in matches:
            lam_home = math.exp(home_advantage + attack[match.home] + defence[match.away])
            lam_away = math.exp(attack[match.away] + defence[match.home])
            log_likelihood += match.weight * (
                match.home_goals * math.log(lam_home)
                - lam_home
                + match.away_goals * math.log(lam_away)
                - lam_away
            )
        if log_likelihood - previous < tolerance:
            break
        previous = log_likelihood

    rho: float | None = None
    if dixon_coles:
        best = -math.inf
        for candidate in _RHO_GRID:
            value = 0.0
            for match in matches:
                lam_home = math.exp(home_advantage + attack[match.home] + defence[match.away])
                lam_away = math.exp(attack[match.away] + defence[match.home])
                tau = _tau(match.home_goals, match.away_goals, lam_home, lam_away, candidate)
                if tau <= 0:
                    value = -math.inf
                    break
                value += match.weight * math.log(tau)
            if value > best:
                best = value
                rho = candidate

    return TeamRatings(
        attack=attack,
        defence=defence,
        home_advantage=home_advantage,
        rho=rho,
        fitted_matches=len(matches),
        iterations=iteration,
        log_likelihood=log_likelihood,
    )


def predict_match(ratings: TeamRatings, home: str, away: str) -> MatchPrediction:
    """Score-grid outcome probabilities with the optional Dixon-Coles correction."""
    if home not in ratings.attack or away not in ratings.attack:
        raise ValueError(f"unfitted team: {home if home not in ratings.attack else away}")
    if home == away:
        raise ValueError("home and away team must differ")
    lam_home = ratings.lambda_home(home, away)
    lam_away = ratings.lambda_away(home, away)
    rho = ratings.rho or 0.0

    grid: dict[tuple[int, int], float] = {}
    total = 0.0
    for hg in range(MAX_GOALS + 1):
        for ag in range(MAX_GOALS + 1):
            mass = math.exp(-lam_home) * lam_home**hg / math.factorial(hg)
            mass *= math.exp(-lam_away) * lam_away**ag / math.factorial(ag)
            mass *= _tau(hg, ag, lam_home, lam_away, rho)
            grid[(hg, ag)] = max(0.0, mass)
            total += grid[(hg, ag)]
    probabilities = {score: mass / total for score, mass in grid.items()}
    home_win = sum(mass for (hg, ag), mass in probabilities.items() if hg > ag)
    draw = sum(mass for (hg, ag), mass in probabilities.items() if hg == ag)
    away_win = sum(mass for (hg, ag), mass in probabilities.items() if hg < ag)
    top_scores = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)[:5]
    return MatchPrediction(
        home=home,
        away=away,
        expected_home_goals=lam_home,
        expected_away_goals=lam_away,
        home_win=home_win,
        draw=draw,
        away_win=away_win,
        most_likely_scores=tuple((f"{hg}-{ag}", mass) for (hg, ag), mass in top_scores),
    )


def walk_forward_backtest(
    matches: Sequence[Match],
    *,
    minimum_train: int = 600,
    refresh_every: int = 60,
    dixon_coles: bool = False,
) -> dict[str, Any]:
    """Evaluate time-ordered predictions where every fit precedes its targets.

    Ratings refresh every ``refresh_every`` evaluated matches; each block of targets
    uses only strictly earlier matches. Baselines are the uniform 1/3 guess and the
    empirical train-window outcome frequencies frozen at first evaluation.
    """
    ordered = list(matches)
    if len(ordered) < minimum_train + 1:
        raise ValueError("not enough matches for a walk-forward split")
    for earlier, later in zip(ordered, ordered[1:]):
        if earlier.kickoff > later.kickoff:
            raise ValueError("matches must be sorted by kickoff before backtesting")

    results: dict[str, Any] = {
        "predictions": [],
        "baseline_uniform": [1 / 3, 1 / 3, 1 / 3],
    }
    ratings: TeamRatings | None = None
    since_refresh = refresh_every
    base_rates: tuple[float, float, float] | None = None

    def metrics(rows: list[tuple[tuple[float, float, float], Match]]) -> dict[str, float]:
        outcomes = {"H": 0, "D": 1, "A": 2}

        def score(probs: tuple[float, float, float], match: Match) -> tuple[float, float, bool]:
            index = outcomes["H" if match.home_goals > match.away_goals else "D" if match.home_goals == match.away_goals else "A"]
            loss = -math.log(max(probs[index], 1e-12))
            brier = sum((p - (1.0 if k == index else 0.0)) ** 2 for k, p in enumerate(probs))
            return loss, brier, probs.index(max(probs)) == index

        summary: dict[str, float] = {}
        for label in ("model", "uniform", "train_rates"):
            losses, briers, correct = [], [], 0
            for row in rows:
                probs = row[0] if label == "model" else results["baseline_uniform"] if label == "uniform" else base_rates
                assert probs is not None
                loss, brier, hit = score(probs, row[1])
                losses.append(loss)
                briers.append(brier)
                correct += hit
            count = len(rows)
            summary[f"{label}_log_loss"] = round(sum(losses) / count, 6)
            summary[f"{label}_brier"] = round(sum(briers) / count, 6)
            summary[f"{label}_accuracy"] = round(correct / count, 6)
        summary["evaluated"] = count
        return summary

    pending: list[tuple[tuple[float, float, float], Match]] = []
    for index, match in enumerate(ordered):
        if index < minimum_train:
            continue
        if ratings is None or since_refresh >= refresh_every:
            ratings = fit_team_ratings(
                ordered[:index],
                dixon_coles=dixon_coles,
            )
            history = ordered[:index]
            counts = [0, 0, 0]
            for past in history:
                if past.home_goals > past.away_goals:
                    counts[0] += 1
                elif past.home_goals == past.away_goals:
                    counts[1] += 1
                else:
                    counts[2] += 1
            base_rates = tuple(count / len(history) for count in counts)
            since_refresh = 0
        # A team never seen before the cutoff (e.g. a promoted club) has no ratings;
        # skip rather than crash, mirroring production behaviour.
        if match.home not in ratings.attack or match.away not in ratings.attack:
            continue
        prediction = predict_match(ratings, match.home, match.away)
        pending.append(((prediction.home_win, prediction.draw, prediction.away_win), match))
        results["predictions"].append(
            {
                **prediction.to_dict(),
                "kickoff": match.kickoff,
                "actual_score": f"{match.home_goals}-{match.away_goals}",
            }
        )
        since_refresh += 1

    if not pending:
        raise ValueError("no evaluated matches; increase sample or lower minimum_train")
    results["summary"] = metrics(pending)
    results["rho"] = ratings.rho if ratings else None
    results["refreshes"] = len(ordered) - minimum_train
    return results

