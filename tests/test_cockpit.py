from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from fplengine.cockpit import (
    assemble_cockpit,
    player_detail,
    render_text,
    snapshot_changes,
)
from fplengine.model import ExpectedPointsModel
from fplengine.rules import validate_squad, RulePlayer
from fplengine.storage import Store
from fplengine.api_client import Snapshot


def _league_snapshot(**overrides) -> Snapshot:
    """Eight clubs x ~4 players so a legal 15-player squad exists with <=3 per club."""
    teams = [
        {
            "id": club_id,
            "code": club_id,
            "name": f"Club {club_id}",
            "short_name": f"C{club_id}",
            "played": 2,
            "strength_attack_home": 1000 + club_id * 10,
            "strength_attack_away": 990 + club_id * 10,
            "strength_defence_home": 1000,
            "strength_defence_away": 990,
        }
        for club_id in range(1, 9)
    ]
    players = []
    player_id = 0
    layout = [(1, 2), (2, 5), (3, 5), (4, 3)]  # (element_type, count) per squad quota
    for element_type, count in layout:
        for index in range(count):
            player_id += 1
            team_id = ((player_id - 1) % 8) + 1
            players.append(
                {
                    "id": player_id,
                    "code": 9000 + player_id,
                    "web_name": f"P{player_id}",
                    "first_name": "Test",
                    "second_name": str(player_id),
                    "element_type": element_type,
                    "team": team_id,
                    "can_select": True,
                    "removed": False,
                    "status": "a",
                    "chance_of_playing_next_round": None,
                    "selected_by_percent": f"{(player_id * 7) % 60}.0",
                    "now_cost": 45 + (player_id % 5) * 5,
                    "starts": 2,
                    "minutes": 170,
                    "expected_goals": f"{0.05 * (player_id % 6):.2f}",
                    "expected_assists": "0.20",
                    "defensive_contribution": 8,
                    "saves": 4 if element_type == 1 else 0,
                    "yellow_cards": 0,
                    "red_cards": 0,
                    "transfers_in_event": 500 + player_id * 10,
                    "transfers_out_event": 200,
                    "total_points": 12,
                    "event_points": 2,
                    "expected_goals_conceded": "2.0",
                    "news": "",
                    "opta_code": f"p{player_id}",
                    "penalties_order": None,
                    "direct_freekicks_order": None,
                    "corners_and_indirect_freekicks_order": None,
                }
            )
    bootstrap = {
        "events": [
            {"id": 2, "is_current": True, "is_next": False, "finished": False},
            {
                "id": 3,
                "is_current": False,
                "is_next": True,
                "finished": False,
                "deadline_time": "2026-09-01T10:00:00Z",
            },
        ],
        "elements": players,
        "teams": teams,
        "element_types": [{"id": value} for value in range(1, 5)],
        "total_players": 1_000_000,
    }
    fixtures = [
        {
            "id": 10,
            "event": 3,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": "2026-09-01T12:00:00Z",
            "team_h_score": None,
            "team_a_score": None,
            "started": False,
            "finished": False,
        }
    ]
    fetched_at = overrides.get("fetched_at")
    snapshot = Snapshot.from_payloads(bootstrap, fixtures, fetched_at)
    if "mutate" in overrides:
        overrides["mutate"](bootstrap)
        snapshot = Snapshot.from_payloads(
            bootstrap,
            [dict(fixture) for fixture in fixtures],
            fetched_at,
        )
    return snapshot


class CockpitAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = _league_snapshot()
        cls.predictions = ExpectedPointsModel().predict(cls.snapshot)

    def test_sections_are_present_and_ranked_rows_explain_themselves(self) -> None:
        cockpit = assemble_cockpit(self.snapshot, self.predictions, limit=10)
        self.assertEqual(cockpit["metadata"]["target_event"], 3)
        self.assertEqual(cockpit["fixtures"][0]["home"], "C1")
        self.assertTrue(cockpit["rankings"])
        top = cockpit["rankings"][0]
        self.assertIn("rank", top)
        self.assertIn("why_top_components", top)
        self.assertTrue(cockpit["captains"])
        ceiling = cockpit["captains"][0]["ceiling_upper_bound"]
        self.assertGreaterEqual(ceiling, cockpit["captains"][0]["expected_points"])
        self.assertFalse(cockpit["changes_since_previous_snapshot"]["available"])

    def test_benchmark_squad_is_rules_valid(self) -> None:
        cockpit = assemble_cockpit(self.snapshot, self.predictions, limit=5)
        squad = cockpit["benchmark_squad"]
        self.assertNotIn("error", squad)
        self.assertEqual(len(squad["squad"]), 15)
        validate_squad(
            [
                RulePlayer(
                    row["player_id"],
                    row["position"],
                    row["team_id"],
                    int(round(row["price"] * 10)),
                )
                for row in squad["squad"]
            ],
            1000,
        )

    def test_personal_transfer_plan_from_squad_file(self) -> None:
        by_position: dict[str, list[int]] = {}
        for row in self.predictions:
            by_position.setdefault(row.position, []).append(row.player_id)
        current_ids = (
            by_position["GK"][:2]
            + by_position["DEF"][:5]
            + by_position["MID"][:5]
            + by_position["FWD"][:3]
        )
        with tempfile.TemporaryDirectory() as tmp:
            squad_path = Path(tmp) / "squad.json"
            squad_path.write_text(
                json.dumps({"player_ids": current_ids, "bank": 15.0, "free_transfers": 2}),
                encoding="utf-8",
            )
            cockpit = assemble_cockpit(
                self.snapshot, self.predictions, squad_file=squad_path
            )
        plan = cockpit["your_transfers"]
        self.assertNotIn("error", plan)
        self.assertGreaterEqual(plan["transfers_used"], 0)

    def test_invalid_squad_files_fail_inside_their_section(self) -> None:
        cases = [
            {"player_ids": [1] * 14, "bank": 1.0, "free_transfers": 1},
            {"player_ids": [1] * 15},
            {"player_ids": [1] * 15, "bank": 1.0, "free_transfers": 9},
        ]
        for payload in cases:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "squad.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                cockpit = assemble_cockpit(
                    self.snapshot, self.predictions, squad_file=path
                )
            self.assertIn("error", cockpit["your_transfers"])

    def test_player_detail_by_name_and_unknown_query_errors_cleanly(self) -> None:
        detail = player_detail(self.snapshot, self.predictions, "P3")
        self.assertEqual(detail["player_id"], 3)
        self.assertIn("why_top_components", detail)
        with self.assertRaises(ValueError):
            player_detail(self.snapshot, self.predictions, "Nobody")

    def test_render_text_contains_decision_sections(self) -> None:
        cockpit = assemble_cockpit(self.snapshot, self.predictions, limit=5, player_query="P3")
        text = render_text(cockpit)
        for marker in ("Decision Cockpit", "Fixtures", "Rankings", "Captain candidates",
                       "Market movers", "Benchmark squad", "uncertainty"):
            self.assertIn(marker, text)


class SnapshotChangeTests(unittest.TestCase):
    def test_diff_between_two_ingestions_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(f"sqlite:///{Path(tmp).joinpath('test.db').as_posix()}")
            store.initialize()
            first = _league_snapshot(fetched_at=datetime(2026, 8, 30, tzinfo=UTC))

            def mutate(bootstrap: dict) -> None:
                row = bootstrap["elements"][0]
                row["now_cost"] = row["now_cost"] + 1
                row["selected_by_percent"] = "44.4"
                row["status"] = "d"
                row["news"] = "Doubtful - ankle"

            second = _league_snapshot(fetched_at=datetime(2026, 8, 31, tzinfo=UTC), mutate=mutate)
            store.save_snapshot(first)
            changes = snapshot_changes(store)
            self.assertFalse(changes["available"])
            store.save_snapshot(second)
            changes = snapshot_changes(store)
            self.assertTrue(changes["available"])
            moved = next(row for row in changes["price_moves"] if row["player_id"] == 1)
            self.assertEqual(moved["price_change"], 0.1)
            self.assertIn("Doubtful", moved["news"])
            riser = next(row for row in changes["ownership_risers"] if row["player_id"] == 1)
            self.assertGreater(riser["ownership_change_pp"], 30)


if __name__ == "__main__":
    unittest.main()
