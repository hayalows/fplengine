from __future__ import annotations

import math
import random
import unittest

from fplengine.team_model import (
    Match,
    TeamRatings,
    canonical_team_name,
    fit_team_ratings,
    predict_match,
    walk_forward_backtest,
)


def _log_likelihood(matches, attack, defence, home_advantage):
    total = 0.0
    for match in matches:
        lam_home = math.exp(home_advantage + attack[match.home] + defence[match.away])
        lam_away = math.exp(attack[match.away] + defence[match.home])
        total += match.weight * (
            match.home_goals * math.log(lam_home)
            - lam_home
            + match.away_goals * math.log(lam_away)
            - lam_away
        )
    return total


def _numerical_gradient(matches, ratings, eps=1e-6):
    gradients = {}
    for name, table in (("a", dict(ratings.attack)), ("d", dict(ratings.defence))):
        for team in table:
            plus = dict(table); plus[team] += eps
            minus = dict(table); minus[team] -= eps
            if name == "a":
                hi = _log_likelihood(matches, plus, ratings.defence, ratings.home_advantage)
                lo = _log_likelihood(matches, minus, ratings.defence, ratings.home_advantage)
            else:
                hi = _log_likelihood(matches, ratings.attack, plus, ratings.home_advantage)
                lo = _log_likelihood(matches, ratings.attack, minus, ratings.home_advantage)
            gradients[f"{name}:{team}"] = (hi - lo) / (2 * eps)
    ha_plus = _log_likelihood(matches, ratings.attack, ratings.defence, ratings.home_advantage + eps)
    ha_minus = _log_likelihood(matches, ratings.attack, ratings.defence, ratings.home_advantage - eps)
    gradients["ha"] = (ha_plus - ha_minus) / (2 * eps)
    return gradients


def _balanced_matches() -> list[Match]:
    """Six equal teams, double round-robin with mirrored scores: zero home advantage."""
    teams = [f"T{index}" for index in range(6)]
    matches = []
    goals = 1
    for first in range(len(teams)):
        for second in range(first + 1, len(teams)):
            home_goals = (goals * 7) % 4
            away_goals = (goals * 3) % 4
            kickoff_a = f"2025-01-{goals % 27 + 1:02d}"
            kickoff_b = f"2025-01-{(goals + 13) % 27 + 1:02d}"
            matches.append(
                Match(teams[first], teams[second], home_goals, away_goals, kickoff=kickoff_a)
            )
            matches.append(
                Match(teams[second], teams[first], away_goals, home_goals, kickoff=kickoff_b)
            )
            goals += 1
    return sorted(matches, key=lambda match: match.kickoff)


def _strong_weak_matches() -> list[Match]:
    """One dominant team and one weak team meeting many times with a strong home edge."""
    matches = []
    for game in range(40):
        matches.append(Match("Giant", "Minnow", 3, 0, kickoff=f"2025-02-{game + 1:02d}"))
        matches.append(Match("Minnow", "Giant", 0, 2, kickoff=f"2025-02-{game + 41:02d}"))
    return matches


class FitTests(unittest.TestCase):
    def test_symmetric_league_gives_symmetric_teams(self) -> None:
        ratings = fit_team_ratings(_balanced_matches())
        attacks = [ratings.attack[team] for team in ratings.attack]
        self.assertAlmostEqual(sum(attacks), 0.0, places=8)
        prediction = predict_match(ratings, "T1", "T2")
        # Fixture data is mirrored per pair but not perfectly label-symmetric, so
        # allow a small tolerance around the exact-symmetry ideal.
        self.assertAlmostEqual(prediction.home_win, prediction.away_win, delta=0.02)
        self.assertAlmostEqual(
            prediction.home_win + prediction.draw + prediction.away_win, 1.0, places=6
        )

    def test_strength_ordering_and_home_advantage(self) -> None:
        ratings = fit_team_ratings(_strong_weak_matches())
        self.assertGreater(ratings.attack["Giant"], ratings.attack["Minnow"])
        self.assertLess(ratings.defence["Giant"], ratings.defence["Minnow"])
        self.assertGreater(ratings.home_advantage, math.log(1.0))
        favourite_home = predict_match(ratings, "Giant", "Minnow")
        favourite_away = predict_match(ratings, "Minnow", "Giant")
        self.assertGreater(favourite_home.home_win, favourite_away.home_win)

    def test_dixon_coles_keeps_probabilities_normalised(self) -> None:
        ratings = fit_team_ratings(_strong_weak_matches(), dixon_coles=True)
        self.assertIsNotNone(ratings.rho)
        prediction = predict_match(ratings, "Giant", "Minnow")
        total = prediction.home_win + prediction.draw + prediction.away_win
        self.assertAlmostEqual(total, 1.0, places=6)
        plain = predict_match(fit_team_ratings(_strong_weak_matches()), "Giant", "Minnow")
        self.assertGreaterEqual(prediction.draw, plain.draw - 1e-9)

    def test_insufficient_or_invalid_input_rejected(self) -> None:
        with self.assertRaises(ValueError):
            fit_team_ratings([Match("A", "B", 1, 0)])
        with self.assertRaises(ValueError):
            Match("A", "A", 1, 1)
        with self.assertRaises(ValueError):
            Match("A", "B", -1, 0)

    def test_solution_is_a_stationary_point_of_the_likelihood(self) -> None:
        matches = sorted(
            _balanced_matches() + _strong_weak_matches()[:20],
            key=lambda match: match.kickoff,
        )
        ratings = fit_team_ratings(matches)
        gradients = _numerical_gradient(matches, ratings)
        worst = max(abs(value) for value in gradients.values())
        self.assertLess(worst, 1e-3, f"non-stationary gradient {worst} at optimum")

    def test_likelihood_is_non_decreasing_across_sweeps(self) -> None:
        matches = sorted(
            _balanced_matches() + _strong_weak_matches()[:30],
            key=lambda match: match.kickoff,
        )
        coarse = fit_team_ratings(matches, max_iterations=5)
        fine = fit_team_ratings(matches, max_iterations=200)
        self.assertGreaterEqual(fine.log_likelihood, coarse.log_likelihood - 1e-9)

    def test_recovers_simulated_lambdas_from_known_parameters(self) -> None:
        truth_attack = {"Big": 0.55, "Mid": 0.05, "Small": -0.60}
        truth_defence = {"Big": -0.35, "Mid": 0.02, "Small": 0.33}
        truth_home_advantage = 0.28
        generator = random.Random(7)
        matches = []
        for game in range(600):
            teams = list(truth_attack)
            home, away = generator.sample(teams, 2)
            lam_home = math.exp(
                truth_home_advantage + truth_attack[home] + truth_defence[away]
            )
            lam_away = math.exp(truth_attack[away] + truth_defence[home])
            home_goals = min(9, _poisson_draw(generator, lam_home))
            away_goals = min(9, _poisson_draw(generator, lam_away))
            matches.append(Match(home, away, home_goals, away_goals))
        ratings = fit_team_ratings(matches)
        # Gauge invariance means parameters are only identified up to a shift between
        # attack and defence; the fitted lambdas must nonetheless match the truth.
        errors = []
        for match in matches[:120]:
            true_home = math.exp(
                truth_home_advantage + truth_attack[match.home] + truth_defence[match.away]
            )
            true_away = math.exp(truth_attack[match.away] + truth_defence[match.home])
            fit_home = math.exp(
                ratings.home_advantage + ratings.attack[match.home] + ratings.defence[match.away]
            )
            fit_away = math.exp(ratings.attack[match.away] + ratings.defence[match.home])
            errors.append(abs(fit_home - true_home) / true_home)
            errors.append(abs(fit_away - true_away) / true_away)
        mean_relative_error = sum(errors) / len(errors)
        self.assertLess(mean_relative_error, 0.10)

    def test_unseen_teams_use_flagged_league_average_prior(self) -> None:
        matches = sorted(_strong_weak_matches(), key=lambda match: match.kickoff)
        ratings = fit_team_ratings(matches)
        prediction = predict_match(ratings, "Newcomer", "Giant")
        self.assertEqual(prediction.priors_used, ("Newcomer",))
        total = prediction.home_win + prediction.draw + prediction.away_win
        self.assertAlmostEqual(total, 1.0, places=6)
        with self.assertRaisesRegex(ValueError, "unfitted team"):
            predict_match(ratings, "Giant", "Newcomer", allow_prior=False)


def _poisson_draw(generator: random.Random, rate: float) -> int:
    limit = math.exp(-rate)
    probability = generator.random()
    draw, term = 0, limit
    while probability > term:
        draw += 1
        term += limit * rate**draw / math.factorial(draw)
    return draw


class CanonicalIdentityTests(unittest.TestCase):
    def test_known_aliases_collapse_to_one_slug(self) -> None:
        for spelling in ("Man City", "Manchester City", "MAN CITY"):
            self.assertEqual(canonical_team_name(spelling), "manchester-city")
        for spelling in ("Spurs", "Tottenham Hotspur"):
            self.assertEqual(canonical_team_name(spelling), "tottenham-hotspur")
        for spelling in ("Nott'm Forest", "Nottingham Forest"):
            self.assertEqual(canonical_team_name(spelling), "nottingham-forest")

    def test_unknown_names_pass_through(self) -> None:
        self.assertEqual(canonical_team_name("FC Graz"), "FC Graz")


class BacktestTests(unittest.TestCase):
    def test_walk_forward_respects_time_and_beats_uniform(self) -> None:
        matches = sorted(
            _strong_weak_matches() + _balanced_matches(),
            key=lambda match: match.kickoff,
        )
        # Pad the league so minimum_train is reachable in a fast unit test.
        extra = []
        for game in range(60):
            for pair in (("T1", "T2"), ("T3", "T4"), ("T5", "T6")):
                extra.append(Match(*pair, 2, 1, kickoff=f"2025-03-{game + 1:02d}"))
                extra.append(Match(*reversed(pair), 1, 0, kickoff=f"2025-03-{game + 1:02d}"))
        matches = sorted(matches + extra, key=lambda match: match.kickoff)
        report = walk_forward_backtest(
            matches, minimum_train=100, refresh_every=80
        )
        summary = report["summary"]
        # Newly seen teams before their first ratings refresh are skipped.
        self.assertGreater(summary["evaluated"], (len(matches) - 100) * 0.8)
        self.assertLessEqual(summary["evaluated"], len(matches) - 100)
        self.assertLess(summary["model_log_loss"], summary["uniform_log_loss"])

    def test_unsorted_matches_are_rejected(self) -> None:
        matches = [
            Match("A", "B", 1, 0, kickoff="2025-01-02"),
            Match("A", "C", 1, 0, kickoff="2025-01-03"),
            Match("B", "C", 2, 1, kickoff="2025-01-04"),
            Match("A", "B", 1, 0, kickoff="2025-01-05"),
            Match("A", "B", 1, 0, kickoff="2025-01-06"),
        ]
        shuffled = [matches[0], matches[2], matches[1], matches[3], matches[4]]
        with self.assertRaisesRegex(ValueError, "sorted"):
            walk_forward_backtest(shuffled, minimum_train=2, refresh_every=1)


if __name__ == "__main__":
    unittest.main()

