from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from fplengine.market import (
    MARKET_PROVENANCE,
    build_market_view,
    hours_between,
    market_events,
    parse_timestamp,
    player_market_row,
    pressure_level,
    select_reference_polls,
)
from fplengine.market_run import market_source_hash, run_once
from fplengine.storage import Store


def _element(player_id: int, **overrides) -> dict:
    row = {
        "id": player_id,
        "now_cost": 70,
        "selected_by_percent": "40.0",
        "transfers_in_event": 5000,
        "transfers_out_event": 1000,
        "status": "a",
        "chance_of_playing_next_round": None,
        "news": "",
    }
    row.update(overrides)
    return row


def _iso(moment: datetime) -> str:
    return moment.isoformat()


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


class MarketSourceHashTests(unittest.TestCase):
    def test_hash_ignores_cosmetic_fields_and_is_stable(self) -> None:
        first = _element(1, web_name="Player", photo="x.jpg")
        second = _element(1, web_name="Renamed", photo="y.jpg")
        third = _element(1, transfers_in_event=6000)
        self.assertEqual(market_source_hash([first]), market_source_hash([second]))
        self.assertNotEqual(market_source_hash([first]), market_source_hash([third]))


class TimestampTests(unittest.TestCase):
    def test_parse_timestamp_handles_z_and_invalid(self) -> None:
        parsed = parse_timestamp("2026-08-24T10:00:00Z")
        self.assertEqual(parsed.hour, 10)
        self.assertIsNone(parse_timestamp("not-a-date"))
        self.assertIsNone(parse_timestamp(None))

    def test_hours_between_clamps_negative_gaps(self) -> None:
        later = NOW
        earlier = NOW - timedelta(hours=3)
        self.assertAlmostEqual(hours_between(later, earlier), 3.0)
        self.assertEqual(hours_between(earlier, later), 0.0)


class ReferencePollTests(unittest.TestCase):
    def _poll(self, poll_id: int, age_hours: float) -> dict:
        return {"id": poll_id, "captured_at": _iso(NOW - timedelta(hours=age_hours))}

    def test_newest_poll_within_each_window_wins(self) -> None:
        polls = [
            self._poll(1, 0.2),
            self._poll(2, 1.5),
            self._poll(3, 7.0),
            self._poll(4, 30.0),
            self._poll(5, 48.0),
        ]
        references = select_reference_polls(polls, NOW)
        # Newest poll that is at least ~75% of the window old wins.
        self.assertEqual(references[1.0]["poll_id"], 2)
        self.assertEqual(references[6.0]["poll_id"], 3)
        self.assertEqual(references[24.0]["poll_id"], 4)

    def test_short_history_leaves_windows_unfilled(self) -> None:
        references = select_reference_polls([self._poll(1, 0.1)], NOW)
        for window in (1.0, 6.0, 24.0):
            self.assertIsNone(references[window])

    def test_current_poll_is_never_its_own_reference(self) -> None:
        # Even when schedule pauses make the newest poll old enough to qualify,
        # comparing it against itself would report zero movement.
        polls = [self._poll(1, 2.0)]
        references = select_reference_polls(polls, NOW, exclude_ids={1})
        for window in (1.0, 6.0, 24.0):
            self.assertIsNone(references[window])


class PlayerMarketRowTests(unittest.TestCase):
    def _current(self, **overrides) -> dict:
        state = {
            "player_id": 9,
            "now_cost": 72,
            "selected_percent": 42.0,
            "transfers_in_event": 90000,
            "transfers_out_event": 10000,
            "status": "a",
            "chance_next": None,
            "news": "",
        }
        state.update(overrides)
        return state

    def test_deltas_velocity_and_price_change_are_calculated(self) -> None:
        current = self._current()
        refs = {
            1.0: (self._current(transfers_in_event=88000), 1.0),
            6.0: (
                self._current(
                    transfers_in_event=70000,
                    now_cost=71,
                    selected_percent=41.0,
                ),
                5.5,
            ),
            24.0: (
                self._current(transfers_in_event=30000, selected_percent=39.5, now_cost=70),
                24.0,
            ),
        }
        history = [
            ("2026-08-23T06:00:00+00:00", 70),
            ("2026-08-24T02:00:00+00:00", 71),
            ("2026-08-24T09:00:00+00:00", 72),
        ]
        row = player_market_row(9, current, refs, history)
        self.assertEqual(row["net_transfers"], 80000)
        self.assertEqual(row["net_transfers_1h"], 2000)
        self.assertEqual(row["net_transfers_6h"], 20000)
        self.assertEqual(row["net_transfers_24h"], 60000)
        self.assertAlmostEqual(row["velocity_per_hour_6h"], round(20000 / 5.5, 1))
        self.assertEqual(row["price"], 7.2)
        self.assertEqual(row["price_change_24h"], 0.2)
        self.assertAlmostEqual(row["ownership_change_24h"], 2.5)
        self.assertEqual(row["last_price_change_at"], "2026-08-24T02:00:00+00:00")
        # 2,000 net in the last hour vs ~3,636/h across the 6h window = cooling.
        self.assertIsNotNone(row["acceleration"])
        self.assertLess(row["acceleration"], 1.0)
        self.assertEqual(row["pressure_direction"], "UP")

    def test_missing_reference_state_yields_no_fabricated_deltas(self) -> None:
        row = player_market_row(
            9, self._current(), {6.0: (None, 5.5), 24.0: (None, 24.0)}
        )
        self.assertIsNone(row["net_transfers_6h"])
        self.assertIsNone(row["price_change_24h"])
        self.assertIsNone(row["last_price_change_at"])

    def test_new_player_with_no_history_is_low_but_directional(self) -> None:
        # No rate is computable (level LOW), but the observed net GW total still
        # gives an honest direction.
        row = player_market_row(9, self._current(), {})
        self.assertEqual(row["pressure_direction"], "UP")
        self.assertEqual(row["pressure_level"], "LOW")

    def test_downward_pressure_detected_from_selling(self) -> None:
        current = self._current(transfers_in_event=1000, transfers_out_event=40000)
        refs = {6.0: (self._current(), 6.0)}
        row = player_market_row(9, current, refs)
        self.assertEqual(row["pressure_direction"], "DOWN")
        self.assertEqual(row["net_transfers_6h"], -119000)

    def test_zero_elapsed_time_does_not_divide_by_zero(self) -> None:
        row = player_market_row(9, self._current(), {6.0: (self._current(), 0.0)})
        self.assertIsNone(row["velocity_per_hour_6h"])
        self.assertEqual(row["pressure_level"], "LOW")


class PressureLevelTests(unittest.TestCase):
    def test_threshold_ladder(self) -> None:
        self.assertEqual(pressure_level(0.01, None), "LOW")
        self.assertEqual(pressure_level(0.10, None), "MEDIUM")
        self.assertEqual(pressure_level(0.50, None), "HIGH")
        self.assertEqual(pressure_level(5.0, None), "VERY HIGH")

    def test_acceleration_boosts_but_is_capped(self) -> None:
        baseline = pressure_level(0.20, None)
        boosted = pressure_level(0.20, 3.0)
        capped_equal = pressure_level(0.20, 9.0)
        self.assertEqual(baseline, "MEDIUM")
        self.assertEqual(boosted, "HIGH")
        self.assertEqual(capped_equal, pressure_level(0.20, 2.5))


def _store_with_history(db_path: Path) -> Store:
    store = Store(f"sqlite:///{db_path.as_posix()}")
    store.initialize()
    base = NOW - timedelta(days=10)    # Four polls: 10d, 6h, 1h and just now; the oldest uses a pre-rise price.
    schedule = [
        (base, [_element(1, now_cost=69), _element(2, now_cost=85)]),
        (
            NOW - timedelta(hours=6),
            [
                _element(1, now_cost=70, transfers_in_event=30000),
                _element(2, now_cost=85, transfers_out_event=900),
            ],
        ),
        (
            NOW - timedelta(hours=1),
            [
                _element(1, now_cost=70, transfers_in_event=45000),
                _element(2, transfers_out_event=1500),
            ],
        ),
        (
            NOW,
            [
                _element(1, now_cost=71, transfers_in_event=52000, news="Knock"),
                _element(2, transfers_out_event=2200, status="d"),
            ],
        ),
    ]
    for index, (moment, elements) in enumerate(schedule):
        poll_id, inserted = store.save_market_poll(
            elements,
            _iso(moment),
            f"{index:064d}",
            event_id=3 if index > 0 else 2,
        )
        assert inserted
    return store


class MarketViewIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = _store_with_history(Path(tmp.name).joinpath("market.db"))
        self.addCleanup(lambda: None)

    def test_view_derives_features_from_real_store_flow(self) -> None:
        polls = self.store.market_polls()
        states = self.store.market_states([row["id"] for row in polls])
        view = build_market_view(polls, states, now=NOW)
        self.assertTrue(view["available"])
        self.assertEqual(view["provenance"], MARKET_PROVENANCE)
        by_id = {row["player_id"]: row for row in view["players"]}
        rising = by_id[1]
        self.assertEqual(rising["price"], 7.1)
        self.assertEqual(rising["price_change_24h"], 0.2)
        self.assertEqual(rising["pressure_direction"], "UP")
        self.assertIsNotNone(rising["last_price_change_at"])
        selling = by_id[2]
        self.assertEqual(selling["pressure_direction"], "DOWN")
        self.assertEqual(selling["status"], "d")

    def test_counter_deltas_never_cross_gameweek_boundaries(self) -> None:
        # The 10-day-old reference belongs to a previous gameweek (event 2) while
        # the newest poll is event 3: official counters reset at deadlines, so the
        # 24h transfer delta is suppressed - but price/ownership stay observable.
        # The 6h reference shares the current gameweek, so its deltas remain.
        polls = self.store.market_polls()
        states = self.store.market_states([row["id"] for row in polls])
        view = build_market_view(polls, states, now=NOW)
        by_id = {row["player_id"]: row for row in view["players"]}
        rising = by_id[1]
        self.assertIsNone(rising["net_transfers_24h"])
        self.assertIsNotNone(rising["net_transfers_6h"])
        self.assertIsNotNone(rising["price_change_24h"])
        self.assertIsNotNone(rising["ownership_change_24h"])

    def test_duplicate_market_state_is_idempotent(self) -> None:
        elements = [_element(1), _element(2)]
        first_id, first_inserted = self.store.save_market_poll(
            elements, _iso(NOW + timedelta(minutes=30)), market_source_hash(elements)
        )
        second_id, second_inserted = self.store.save_market_poll(
            elements, _iso(NOW + timedelta(minutes=60)), market_source_hash(elements)
        )
        self.assertTrue(first_inserted)
        self.assertFalse(second_inserted)
        self.assertEqual(first_id, second_id)

    def test_prune_respects_retention_and_floor(self) -> None:
        # History currently holds the four seeded polls plus nothing stale beyond
        # retention except potentially none; seed two clearly stale extra polls.
        stale_a, _ = self.store.save_market_poll(
            [_element(1)], _iso(NOW - timedelta(days=11)), "a" * 64
        )
        stale_b, _ = self.store.save_market_poll(
            [_element(1)], _iso(NOW - timedelta(days=12)), "b" * 64
        )
        removed = self.store.prune_market_history(retention_days=7, keep_polls=4)
        remaining = [row["id"] for row in self.store.market_polls()]
        self.assertGreaterEqual(removed, 2)
        self.assertNotIn(stale_b, remaining)
        self.assertNotIn(stale_a, remaining)

    def test_player_absent_from_older_snapshot_has_none_deltas(self) -> None:
        new_element = _element(3, now_cost=45, transfers_in_event=900)
        self.store.save_market_poll(
            [new_element], _iso(NOW + timedelta(seconds=1)), "c" * 64
        )
        polls = self.store.market_polls()
        states = self.store.market_states([row["id"] for row in polls])
        view = build_market_view(polls, states, now=NOW + timedelta(seconds=1))
        newcomer = next(
            row for row in view["players"] if row["player_id"] == 3
        )
        self.assertIsNone(newcomer["net_transfers_24h"])
        self.assertIsNotNone(newcomer["net_transfers"])


class MarketEventTests(unittest.TestCase):
    def test_feed_types_and_names(self) -> None:
        view = {
            "available": True,
            "captured_at": _iso(NOW),
            "players": [
                player_market_row(
                    1,
                    {
                        "player_id": 1,
                        "now_cost": 71,
                        "selected_percent": 43.0,
                        "transfers_in_event": 90000,
                        "transfers_out_event": 10000,
                        "status": "a",
                        "chance_next": None,
                        "news": "",
                    },
                    {
                        6.0: (
                            {
                                "player_id": 1,
                                "now_cost": 70,
                                "selected_percent": 41.5,
                                "transfers_in_event": 30000,
                                "transfers_out_event": 1000,
                                "status": "a",
                                "chance_next": None,
                                "news": "",
                            },
                            6.0,
                        )
                    },
                ),
                player_market_row(
                    2,
                    {
                        "player_id": 2,
                        "now_cost": 60,
                        "selected_percent": 12.0,
                        "transfers_in_event": 500,
                        "transfers_out_event": 30000,
                        "status": "a",
                        "chance_next": None,
                        "news": "Illness doubt",
                    },
                    {},
                ),
            ],
        }
        events = market_events(view, {1: "Star", 2: "Doubt"})
        types = [event["type"] for event in events]
        self.assertIn("TRANSFER SURGE", types)
        self.assertIn("NEWS", types)
        star_surge = next(event for event in events if event["type"] == "TRANSFER SURGE")
        self.assertEqual(star_surge["name"], "Star")


class MarketRunTests(unittest.TestCase):
    def test_current_event_resolution(self) -> None:
        from fplengine.market_run import _current_event_id

        events = [
            {"id": 1, "deadline_time": "2026-08-10T18:00:00Z", "finished": True},
            {"id": 2, "deadline_time": "2026-08-24T18:00:00Z", "finished": False},
            {"id": 3, "deadline_time": "2026-08-31T18:00:00Z", "finished": False},
        ]
        # Between GW2's deadline and GW3's, counters accumulate into GW3.
        self.assertEqual(
            _current_event_id(events, "2026-08-24T19:00:00Z"), 3
        )
        # Before GW2's deadline, counters belong to GW2 itself.
        self.assertEqual(
            _current_event_id(events, "2026-08-24T09:00:00Z"), 2
        )

    def test_run_once_persists_poll_and_events_without_model(self) -> None:
        bootstrap = {
            "elements": [_element(1), _element(2)],
            "events": [{"id": 2, "name": "Gameweek 2", "deadline_time": None}],
        }
        with (
            patch("fplengine.market_run.FPLClient") as client_cls,
            patch("fplengine.market_run.Store") as store_cls,
        ):
            client_cls.return_value.bootstrap.return_value = bootstrap
            store = store_cls.return_value
            store.is_postgres = True
            store.save_market_poll.return_value = (31, True)
            store.prune_market_history.return_value = 2

            result = run_once("postgresql://example.invalid/neondb")

            store.save_season_events.assert_called_once()
            args = store.save_market_poll.call_args.args
            kwargs = store.save_market_poll.call_args.kwargs
            self.assertEqual(args[0], bootstrap["elements"])
            self.assertEqual(len(args[2]), 64)
            self.assertIn("event_id", kwargs)
            store.prune_market_history.assert_called_once_with()
            self.assertTrue(result["inserted"])
            self.assertEqual(result["poll_id"], 31)

    def test_run_once_rejects_non_postgres(self) -> None:
        with (
            patch("fplengine.market_run.FPLClient") as client_cls,
            patch("fplengine.market_run.Store") as store_cls,
        ):
            client_cls.return_value.bootstrap.return_value = {"elements": [_element(1)]}
            store_cls.return_value.is_postgres = False
            with self.assertRaisesRegex(RuntimeError, "PostgreSQL production database"):
                run_once("sqlite:///local.db")


if __name__ == "__main__":
    unittest.main()
