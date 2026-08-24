from __future__ import annotations

import math
import unittest

from fplengine.team_model import (
    Match,
    fit_team_ratings,
    predict_match,
    walk_forward_backtest,
)


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
