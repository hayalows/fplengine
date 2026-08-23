from datetime import datetime, timezone

from fplengine.api_client import Snapshot


def player(
    player_id: int,
    team: int,
    position: int,
    *,
    status: str = "a",
    starts: int = 2,
    minutes: int = 170,
    ownership: str = "10.0",
    xg: str = "0.50",
    xa: str = "0.30",
) -> dict:
    return {
        "id": player_id,
        "code": 1000 + player_id,
        "web_name": f"Player {player_id}",
        "first_name": "Test",
        "second_name": str(player_id),
        "element_type": position,
        "team": team,
        "can_select": True,
        "removed": False,
        "status": status,
        "chance_of_playing_next_round": 0 if status == "i" else None,
        "selected_by_percent": ownership,
        "now_cost": 50 if position in {1, 2} else 75,
        "starts": starts,
        "minutes": minutes,
        "expected_goals": xg,
        "expected_assists": xa,
        "defensive_contribution": 12 if position == 2 else 6,
        "saves": 6 if position == 1 else 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "transfers_in_event": 1000,
        "transfers_out_event": 250,
        "total_points": 10,
        "event_points": 2,
        "expected_goals_conceded": "2.0",
        "news": "",
        "opta_code": f"p{player_id}",
        "penalties_order": None,
        "direct_freekicks_order": None,
        "corners_and_indirect_freekicks_order": None,
    }


def snapshot(*, double: bool = False, blank: bool = False) -> Snapshot:
    teams = [
        {
            "id": 1,
            "code": 1,
            "name": "Alpha",
            "short_name": "ALP",
            "played": 2,
            "strength_attack_home": 1100,
            "strength_attack_away": 1050,
            "strength_defence_home": 1100,
            "strength_defence_away": 1050,
        },
        {
            "id": 2,
            "code": 2,
            "name": "Beta",
            "short_name": "BET",
            "played": 2,
            "strength_attack_home": 900,
            "strength_attack_away": 900,
            "strength_defence_home": 900,
            "strength_defence_away": 900,
        },
    ]
    players = [
        player(1, 1, 3, ownership="25", xg="1.2", xa="0.8"),
        player(2, 1, 2),
        player(3, 2, 4, ownership="15", xg="0.8", xa="0.1"),
        player(4, 2, 1),
        player(5, 1, 3, status="i", starts=0, minutes=0),
    ]
    fixtures = [] if blank else [
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
    if double:
        fixtures.append(
            {
                "id": 11,
                "event": 3,
                "team_h": 2,
                "team_a": 1,
                "kickoff_time": "2026-09-04T19:00:00Z",
                "team_h_score": None,
                "team_a_score": None,
                "started": False,
                "finished": False,
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
        "total_players": 1000000,
    }
    return Snapshot.from_payloads(
        bootstrap, fixtures, datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    )
