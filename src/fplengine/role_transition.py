"""Role-transition diagnostics and prior-decay challengers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .benchmark import SeasonArchive
from .historical import _read_csv
from .historical_model import HistoricalExpectedPointsModel

ROLE_EVIDENCE_FIELDS = (
    "games",
    "starts",
    "starts_opportunities",
    "starter_minutes",
    "substitute_appearances",
    "substitute_minutes",
)


@dataclass(frozen=True)
class TransitionProfile:
    player_code: int
    target_team: str
    prior_team: str | None
    same_club: bool
    club_change: bool
    new_to_fpl: bool
    promoted_team: bool

    @property
    def transition(self) -> bool:
        return self.club_change or self.promoted_team

    def labels(self) -> tuple[str, ...]:
        labels = ["all"]
        if self.same_club:
            labels.append("same_club")
        if self.club_change:
            labels.append("club_change")
        if self.new_to_fpl:
            labels.append("new_to_fpl")
        if self.promoted_team:
            labels.append("promoted_team")
        if self.transition:
            labels.append("role_transition")
        else:
            labels.append("no_transition")
        return tuple(labels)


def transition_profiles(
    archive: SeasonArchive,
    prior_payload: dict[str, Any],
    prior_season_dir: Path,
) -> dict[int, TransitionProfile]:
    """Classify target-season players using only pre-season-known information."""
    prior_players = prior_payload.get("players", {})
    prior_team_names = {
        str(row.get("name") or "") for row in _read_csv(prior_season_dir / "teams.csv")
    }
    snapshot = archive.snapshot_before(1)
    target_teams = {
        int(row["id"]): str(row.get("name") or "") for row in snapshot.bootstrap["teams"]
    }
    result: dict[int, TransitionProfile] = {}
    for player in snapshot.bootstrap["elements"]:
        code = int(player.get("code") or 0)
        if not code:
            continue
        target_team = target_teams.get(int(player["team"]), "")
        prior = prior_players.get(str(code))
        prior_team = str(prior.get("team") or "") if prior else None
        new_to_fpl = prior is None
        same_club = bool(prior_team and prior_team == target_team)
        club_change = bool(prior_team and prior_team != target_team)
        promoted_team = bool(target_team and target_team not in prior_team_names)
        result[code] = TransitionProfile(
            player_code=code,
            target_team=target_team,
            prior_team=prior_team,
            same_club=same_club,
            club_change=club_change,
            new_to_fpl=new_to_fpl,
            promoted_team=promoted_team,
        )
    return result


class RoleTransitionExpectedPointsModel(HistoricalExpectedPointsModel):
    """Challenger that down-weights only historical role/minutes evidence.

    Attacking ability and other rate evidence are intentionally left unchanged. The
    experiment asks whether a transfer/promotion should make us less certain about a
    player's *role*, not whether the player forgot how to play football.
    """

    def __init__(
        self,
        *,
        priors: dict[str, Any],
        role_weights: dict[int, float] | None = None,
        model_version: str = "xp-v0.3-role-transition-challenger",
    ) -> None:
        super().__init__(priors=priors, model_version=model_version)
        self.role_weights = role_weights or {}

    def _player_prior(self, player: dict[str, Any]) -> dict[str, Any]:
        prior = super()._player_prior(player)
        if not prior:
            return prior
        code = int(player.get("code") or 0)
        weight = float(self.role_weights.get(code, 1.0))
        weight = min(1.0, max(0.0, weight))
        if weight >= 0.999999:
            return prior
        adjusted = dict(prior)
        for field in ROLE_EVIDENCE_FIELDS:
            if field in adjusted:
                adjusted[field] = float(adjusted[field]) * weight
        return adjusted


def transition_role_weights(
    profiles: dict[int, TransitionProfile],
    *,
    transition_weight: float,
) -> dict[int, float]:
    """Apply one test weight to players whose pre-season context changed."""
    if not 0.0 <= transition_weight <= 1.0:
        raise ValueError("transition_weight must be in [0, 1]")
    return {
        code: transition_weight
        for code, profile in profiles.items()
        if profile.transition
    }
