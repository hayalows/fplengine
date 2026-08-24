import unittest
from collections import Counter

from fplengine.model import Prediction
from fplengine.optimizer import optimize_static_squad, optimize_transfers
from fplengine.rules import SQUAD_POSITION_QUOTAS


def prediction(
    player_id: int,
    *,
    position: str,
    team_id: int,
    xp: float,
    event: int = 2,
    price: float = 5.0,
) -> Prediction:
    return Prediction(
        player_id=player_id,
        player_code=10000 + player_id,
        player_name=f"P{player_id}",
        team_id=team_id,
        team=f"T{team_id}",
        position=position,
        price=price,
        ownership_percent=5.0,
        target_event=event,
        fixture_count=1,
        expected_minutes=80.0,
        expected_points=xp,
        expected_goals=0.2,
        expected_assists=0.15,
        clean_sheet_probability=0.3,
        risk=0.08,
        confidence="medium",
        value_score=xp / price,
        differential_score=xp,
        market_net_transfers=0,
        market_momentum_percent=0.0,
        lower_bound=0.0,
        upper_bound=xp + 4.0,
        model_version="test-xp",
        data_as_of="2026-08-24T00:00:00+00:00",
        components={},
        provenance={},
    )


def market(event: int = 2) -> list[Prediction]:
    rows: list[Prediction] = []
    player_id = 1
    config = {"GK": 8, "DEF": 16, "MID": 16, "FWD": 10}
    for position, count in config.items():
        for index in range(count):
            team_id = index % 10 + 1
            xp = 7.5 - 0.12 * index + (0.2 if position == "MID" else 0.0)
            price = 4.0 + (index % 4) * 0.5
            rows.append(
                prediction(
                    player_id,
                    position=position,
                    team_id=team_id,
                    xp=xp,
                    event=event,
                    price=price,
                )
            )
            player_id += 1
    return rows


class OptimizerTests(unittest.TestCase):
    def test_static_optimizer_obeys_squad_budget_club_and_lineup_rules(self) -> None:
        event2 = market(2)
        event3 = [
            prediction(
                row.player_id,
                position=row.position,
                team_id=row.team_id,
                xp=max(0.1, row.expected_points - 0.4 + (row.player_id % 3) * 0.15),
                event=3,
                price=row.price,
            )
            for row in event2
        ]
        result = optimize_static_squad({2: event2, 3: event3}, budget=100.0)
        self.assertEqual(len(result.squad), 15)
        self.assertLessEqual(result.squad_cost, 100.0)
        self.assertEqual(Counter(row.position for row in result.squad), Counter(SQUAD_POSITION_QUOTAS))
        self.assertLessEqual(max(Counter(row.team_id for row in result.squad).values()), 3)
        self.assertEqual(len(result.lineups), 2)
        for lineup in result.lineups:
            positions = Counter(row.position for row in lineup.starters)
            self.assertEqual(len(lineup.starters), 11)
            self.assertEqual(positions["GK"], 1)
            self.assertGreaterEqual(positions["DEF"], 3)
            self.assertGreaterEqual(positions["MID"], 2)
            self.assertGreaterEqual(positions["FWD"], 1)
            self.assertIn(lineup.captain.player_id, {row.player_id for row in lineup.starters})
            self.assertNotEqual(lineup.captain.player_id, lineup.vice_captain.player_id)

    def test_transfer_optimizer_uses_free_transfer_for_clear_upgrade(self) -> None:
        rows: list[Prediction] = []
        current_ids: list[int] = []
        player_id = 1
        # Build a valid current squad with no more than three per club.
        for position, count in SQUAD_POSITION_QUOTAS.items():
            for index in range(count):
                team_id = (player_id - 1) % 8 + 1
                xp = 4.0
                if position == "MID" and index == 0:
                    xp = 0.5
                rows.append(
                    prediction(
                        player_id,
                        position=position,
                        team_id=team_id,
                        xp=xp,
                        price=5.0,
                    )
                )
                current_ids.append(player_id)
                player_id += 1
        weak_mid = next(row for row in rows if row.position == "MID" and row.expected_points == 0.5)
        upgrade_id = player_id
        rows.append(
            prediction(
                upgrade_id,
                position="MID",
                team_id=9,
                xp=9.0,
                price=5.0,
            )
        )
        # Add unattractive legal alternatives so the market is not degenerate.
        for position in ("GK", "DEF", "MID", "FWD"):
            player_id += 1
            rows.append(
                prediction(
                    player_id,
                    position=position,
                    team_id=10,
                    xp=0.1,
                    price=5.0,
                )
            )
        result = optimize_transfers(
            current_ids,
            {2: rows},
            bank=0.0,
            free_transfers=1,
            max_transfers=1,
        )
        self.assertEqual(result.transfers_used, 1)
        self.assertEqual(result.hit_cost, 0)
        self.assertEqual(result.transfers_in[0].player_id, upgrade_id)
        self.assertEqual(result.transfers_out[0].player_id, weak_mid.player_id)


if __name__ == "__main__":
    unittest.main()
