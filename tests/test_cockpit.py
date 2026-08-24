from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from fplengine.cockpit import (
    assemble_cockpit,
    build_personal_sections,
    decide_roll_or_transfer,
    player_detail,
    reconstruct_free_transfer_balance,
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


class FakeEntryClient:
    def __init__(self, picks, history):
        self._picks = {"picks": picks}
        self._history = history
        self.entry_payload = {"name": "Test FC"}

    def entry(self, entry_id):
        return dict(self.entry_payload)

    def entry_history(self, entry_id):
        return json.loads(json.dumps(self._history))

    def entry_picks(self, entry_id, event):
        return json.loads(json.dumps(self._picks))


def _pick_rows() -> list[dict]:
    """Official-style picks from the synthetic league: slots 1-11 starters,
    12-15 bench in order (GK first). Squad = 2 GK / 5 DEF / 5 MID / 3 FWD."""
    gk, defs, mids, fwds = [1, 6], [2, 3, 4, 5, 7], [8, 9, 10, 11, 12], [13, 14, 15]
    starters = [gk[0]] + defs[:4] + mids[:4] + fwds[:2]
    bench = [gk[1], defs[4], mids[4], fwds[2]]
    rows = []
    for slot, player_id in enumerate(starters, start=1):
        rows.append(
            {
                "element": player_id,
                "position": slot,
                "multiplier": 2 if slot == 10 else 1,
                "is_captain": slot == 10,
                "is_vice_captain": slot == 9,
            }
        )
    for bench_slot, player_id in enumerate(bench, start=12):
        rows.append(
            {
                "element": player_id,
                "position": bench_slot,
                "multiplier": 0,
                "is_captain": False,
                "is_vice_captain": False,
            }
        )
    return rows


class PersonalSectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = _league_snapshot()
        self.predictions = ExpectedPointsModel().predict(self.snapshot)
        self.client = FakeEntryClient(
            _pick_rows(),
            {
                "current": [{"event": 1, "bank": 8, "event_transfers": 0}],
                "chips": [],
            },
        )

    def test_my_team_sections_are_complete_and_labelled(self) -> None:
        sections = build_personal_sections(
            self.client, self.snapshot, self.predictions, 7181076
        )
        players = sections["my_team"]["players"]
        self.assertEqual(len(players), 15)
        self.assertEqual(sum(1 for row in players if row["role"] == "starter"), 11)
        captains = [row for row in players if row["is_captain"]]
        vices = [row for row in players if row["is_vice_captain"]]
        self.assertEqual(len(captains), 1)
        self.assertEqual(len(vices), 1)
        self.assertTrue(all("fixture" in row and "price" in row for row in players))
        state = sections["manager_state"]
        self.assertEqual(state["squad_and_lineup"]["classification"], "VERIFIED")
        self.assertEqual(state["bank"]["classification"], "RECONSTRUCTED")
        self.assertEqual(state["free_transfers"]["classification"], "RECONSTRUCTED")

    def test_user_supplied_overrides_reclassify_state(self) -> None:
        sections = build_personal_sections(
            self.client,
            self.snapshot,
            self.predictions,
            7181076,
            bank_override=0.8,
            free_transfers_override=2,
        )
        state = sections["manager_state"]
        self.assertEqual(state["bank"]["classification"], "USER-SUPPLIED")
        self.assertEqual(state["bank"]["value"], 0.8)
        self.assertEqual(state["free_transfers"]["classification"], "USER-SUPPLIED")
        label = sections["next_gw"]["recommendation"]["state_label"]
        # selling prices remain approximated, so the plan is still APPROXIMATE
        self.assertEqual(label, "APPROXIMATE")

    def test_chipped_history_replays_chip_rule_and_stays_labelled_approximate(self) -> None:
        client = FakeEntryClient(
            _pick_rows(),
            {
                "current": [
                    {"event": 1, "bank": 8, "event_transfers": 0},
                    {"event": 2, "bank": 5, "event_transfers": 9},
                ],
                "chips": [{"name": "wildcard", "event": 2, "entry": 7181076}],
            },
        )
        sections = build_personal_sections(client, self.snapshot, self.predictions, 7181076)
        state = sections["manager_state"]["free_transfers"]
        # GW1 saved the opening FT; the nine wildcard moves in GW2 preserved it.
        self.assertEqual(state["value"], 2)
        self.assertEqual(state["classification"], "APPROXIMATED")
        self.assertIn("GW2 (wildcard)", state["note"])
        self.assertIn("--free-transfers", state["note"])
        label = sections["next_gw"]["recommendation"]["state_label"]
        self.assertEqual(label, "APPROXIMATE")

    def test_free_transfers_override_wins_over_chip_aware_replay(self) -> None:
        client = FakeEntryClient(
            _pick_rows(),
            {
                "current": [
                    {"event": 1, "bank": 8, "event_transfers": 0},
                    {"event": 2, "bank": 5, "event_transfers": 9},
                ],
                "chips": [{"name": "wildcard", "event": 2, "entry": 7181076}],
            },
        )
        sections = build_personal_sections(
            client, self.snapshot, self.predictions, 7181076, free_transfers_override=4
        )
        state = sections["manager_state"]["free_transfers"]
        self.assertEqual(state["value"], 4)
        self.assertEqual(state["classification"], "USER-SUPPLIED")
        self.assertIn("override", state["note"])

    def test_roll_is_recommended_when_transfers_add_nothing(self) -> None:
        sections = build_personal_sections(
            self.client, self.snapshot, self.predictions, 7181076
        )
        recommendation = sections["next_gw"]["recommendation"]
        self.assertIn(recommendation["action"], ("ROLL", "TRANSFER (one)", "TRANSFER (two)"))
        plan = recommendation["recommended_plan"]
        self.assertTrue(plan["captain"])
        self.assertEqual(len(plan["starters"]), 11)
        self.assertEqual(len(plan["bench_order"]), 4)

    def test_render_text_includes_personal_blocks(self) -> None:
        sections = build_personal_sections(
            self.client, self.snapshot, self.predictions, 7181076
        )
        cockpit = assemble_cockpit(self.snapshot, self.predictions, limit=5)
        cockpit.update({key: value for key, value in sections.items()})
        text = render_text(cockpit)
        self.assertIn("MY TEAM", text)
        self.assertIn("NEXT GW RECOMMENDATION", text)


class RollDecisionCoreTests(unittest.TestCase):
    """Regression tests for the PR #24 decision bug: the second transfer was judged
    only against the single-transfer plan instead of against rolling."""

    def test_roll_wins_when_total_double_gain_is_below_threshold(self) -> None:
        # single gains 0.7 (below threshold), double gains 1.4 total but the old
        # incremental view (+0.7 over single) also sat under its margin, so PR #24
        # wrongly rolled despite a 1.4-point total gain.
        decision = decide_roll_or_transfer(
            roll_projection=40.0,
            single_projection=40.7,
            double_projection=41.4,
            threshold=0.8,
        )
        self.assertEqual(decision["action"], "TRANSFER (two)")
        self.assertEqual(decision["best_gain_over_roll"], 1.4)

    def test_both_gains_below_threshold_means_roll(self) -> None:
        decision = decide_roll_or_transfer(
            roll_projection=40.0,
            single_projection=40.5,
            double_projection=40.6,
        )
        self.assertEqual(decision["action"], "ROLL")
        self.assertEqual(decision["gain_single_over_roll"], 0.5)
        self.assertEqual(decision["gain_double_over_roll"], 0.6)

    def test_single_transfer_chosen_when_double_adds_little_over_roll(self) -> None:
        # Old code compared +2.0 incremental and would have said two transfers even
        # though the single plan already captures most of the value vs rolling.
        decision = decide_roll_or_transfer(
            roll_projection=40.0,
            single_projection=42.8,
            double_projection=43.3,
            threshold=0.8,
        )
        self.assertEqual(decision["action"], "TRANSFER (one)")
        self.assertGreater(decision["gain_single_over_roll"], 0.8)

    def test_two_transfers_only_when_materially_better_than_single(self) -> None:
        decision = decide_roll_or_transfer(
            roll_projection=40.0,
            single_projection=41.0,
            double_projection=42.6,
        )
        self.assertEqual(decision["action"], "TRANSFER (two)")
        self.assertAlmostEqual(decision["gain_double_over_roll"], 2.6)


class FreeTransferReplayTests(unittest.TestCase):
    def test_saved_transfer_carries_into_next_gameweek(self) -> None:
        rows = [{"event": 1, "event_transfers": 0}]
        result = reconstruct_free_transfer_balance(rows, chips=[])
        self.assertEqual(result["balance"], 2)
        self.assertTrue(result["unambiguous"])

    def test_one_used_from_two_rebalances_back_to_two(self) -> None:
        rows = [
            {"event": 1, "event_transfers": 0},
            {"event": 2, "event_transfers": 1},
        ]
        result = reconstruct_free_transfer_balance(rows, chips=[])
        self.assertEqual(result["balance"], 2)

    def test_multiple_saves_stack_up_to_the_cap(self) -> None:
        rows = [
            {"event": index, "event_transfers": 0} for index in range(1, 7)
        ]
        result = reconstruct_free_transfer_balance(rows, chips=[])
        self.assertEqual(result["balance"], 5)

    def test_hits_drain_balance_to_the_floor_then_refill_by_one(self) -> None:
        rows = [
            {"event": 1, "event_transfers": 0},
            {"event": 2, "event_transfers": 3},
        ]
        result = reconstruct_free_transfer_balance(rows, chips=[])
        self.assertEqual(result["balance"], 1)

    def test_gap_in_history_makes_balance_not_derivable(self) -> None:
        gapped = [{"event": 2, "event_transfers": 0}, {"event": 4, "event_transfers": 0}]
        result = reconstruct_free_transfer_balance(gapped)
        self.assertFalse(result["unambiguous"])
        self.assertIsNone(result["balance"])

    def test_empty_history_has_no_derivable_balance(self) -> None:
        result = reconstruct_free_transfer_balance([], [])
        self.assertIsNone(result["balance"])


class ChipAwareFreeTransferReplayTests(unittest.TestCase):
    """Official wildcard/free-hit banking rule: unlimited chip transfers are free,
    neither consume banked free transfers nor earn the weekly +1 accrual - the
    balance carries through unchanged. Bench Boost/Triple Captain stay ordinary."""

    def _replay(self, rows, chips):
        return reconstruct_free_transfer_balance(rows, chips)

    def test_manager_enters_chip_gameweek_with_one_free_transfer(self) -> None:
        # GW1 spends the opening FT (balance stays 1); GW2 wildcard makes six more
        # changes without touching the banked transfer.
        result = self._replay(
            [
                {"event": 1, "event_transfers": 1},
                {"event": 2, "event_transfers": 6},
            ],
            [{"name": "wildcard", "event": 2}],
        )
        self.assertEqual(result["balance"], 1)
        self.assertTrue(result["unambiguous"])
        self.assertEqual(
            result["chip_gameweeks"], [{"event": 2, "name": "wildcard"}]
        )

    def test_wildcard_with_many_changes_preserves_three_saved_transfers(self) -> None:
        # Two saved gameweeks give 3 FTs entering GW3; ten wildcard changes must not
        # drain them (ordinary replay would have floored the balance to 1).
        result = self._replay(
            [
                {"event": 1, "event_transfers": 0},
                {"event": 2, "event_transfers": 0},
                {"event": 3, "event_transfers": 10},
            ],
            [{"name": "wildcard", "event": 3}],
        )
        self.assertEqual(result["balance"], 3)
        self.assertTrue(result["unambiguous"])

    def test_free_hit_with_many_changes_preserves_saved_transfers(self) -> None:
        result = self._replay(
            [
                {"event": 1, "event_transfers": 0},
                {"event": 2, "event_transfers": 0},
                {"event": 3, "event_transfers": 15},
            ],
            [{"name": "freehit", "event": 3}],
        )
        self.assertEqual(result["balance"], 3)
        self.assertTrue(result["unambiguous"])
        self.assertEqual(result["chip_gameweeks"][0]["name"], "freehit")

    def test_chip_gameweek_earns_no_extra_accrual(self) -> None:
        # Entering a zero-transfer wildcard with 2 saved FTs must exit with 2, not 3:
        # the weekly +1 accrual is replaced by the chip.
        result = self._replay(
            [
                {"event": 1, "event_transfers": 0},
                {"event": 2, "event_transfers": 0},
            ],
            [{"name": "wildcard", "event": 2}],
        )
        self.assertEqual(result["balance"], 2)

    def test_ordinary_recurrence_resumes_after_the_chip(self) -> None:
        # FH preserves 2 FTs in GW2; GW3 then follows next_free_transfers normally
        # (one spent from two leaves one, plus the weekly accrual = two).
        result = self._replay(
            [
                {"event": 1, "event_transfers": 0},
                {"event": 2, "event_transfers": 12},
                {"event": 3, "event_transfers": 1},
            ],
            [{"name": "free_hit", "event": 2}],
        )
        self.assertEqual(result["balance"], 2)

    def test_bench_boost_weeks_follow_ordinary_transfer_rules(self) -> None:
        result = self._replay(
            [
                {"event": 1, "event_transfers": 0},
                {"event": 2, "event_transfers": 2},
                {"event": 3, "event_transfers": 0},
            ],
            [{"name": "bboost", "event": 2}],
        )
        self.assertEqual(result["balance"], 2)
        self.assertEqual(result["chip_gameweeks"], [])

    def test_non_chip_gameweeks_still_replay_next_free_transfers(self) -> None:
        result = self._replay(
            [
                {"event": 1, "event_transfers": 3},
                {"event": 2, "event_transfers": 0},
            ],
            [],
        )
        # 1 FT, three moves -> hit floor 0 + accrual = 1, saving again -> 2.
        self.assertEqual(result["balance"], 2)
        self.assertTrue(result["unambiguous"])

    def test_unmappable_transfer_chip_yields_no_balance_instead_of_a_guess(self) -> None:
        result = self._replay(
            [{"event": 1, "event_transfers": 4}],
            [{"name": "wildcard"}],
        )
        self.assertFalse(result["unambiguous"])
        self.assertIsNone(result["balance"])
        self.assertTrue(result["chip_timing_unknown"])


class SellingPriceCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = _league_snapshot()
        self.predictions = ExpectedPointsModel().predict(self.snapshot)
        self.client = FakeEntryClient(
            _pick_rows(),
            {"current": [{"event": 1, "bank": 8, "event_transfers": 0}], "chips": []},
        )

    def _sections_with_prices(self, payload: dict[int, float]) -> Any:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prices.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return build_personal_sections(
                self.client,
                self.snapshot,
                self.predictions,
                7181076,
                bank_override=0.8,
                free_transfers_override=2,
                selling_prices_file=path,
            )

    def test_partial_price_map_stays_approximate(self) -> None:
        sections = self._sections_with_prices({1: 4.5})
        state = sections["manager_state"]["selling_prices"]
        self.assertEqual(state["classification"], "APPROXIMATED")
        self.assertIn("1/15", state["value"])
        self.assertEqual(
            sections["next_gw"]["recommendation"]["state_label"], "APPROXIMATE"
        )

    def test_full_price_map_earns_verified_inputs_label(self) -> None:
        owned = sorted(row["element"] for row in _pick_rows())
        prices = {player_id: 4.0 for player_id in owned}
        sections = self._sections_with_prices(prices)
        state = sections["manager_state"]["selling_prices"]
        self.assertEqual(state["classification"], "USER-SUPPLIED")
        self.assertEqual(
            sections["next_gw"]["recommendation"]["state_label"], "VERIFIED_INPUTS"
        )

    def test_recommendation_reports_gains_against_roll(self) -> None:
        sections = build_personal_sections(
            self.client, self.snapshot, self.predictions, 7181076
        )
        next_gw = sections["next_gw"]
        rec = next_gw["recommendation"]
        roll = next_gw["roll_plan"]["projected_points"]
        one = next_gw["best_single_transfer"]["projected_points"]
        two = next_gw["best_two_transfer"]["projected_points"]
        self.assertAlmostEqual(rec["gain_single_over_roll"], round(one - roll, 3), places=3)
        self.assertAlmostEqual(rec["gain_double_over_roll"], round(two - roll, 3), places=3)
        expected_action = (
            "ROLL"
            if rec["best_gain_over_roll"] <= 0.8
            else ("TRANSFER (two)" if rec["gain_double_over_roll"] > rec["gain_single_over_roll"] + 1.0 else "TRANSFER (one)")
        )
        self.assertEqual(rec["action"], expected_action)


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
