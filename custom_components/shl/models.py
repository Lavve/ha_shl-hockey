"""Data models for the SHL integration.

Plain dataclasses with raw values (UTC datetimes, ints). Formatting for
the user's language and locale is left to Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .const import STATE_POST_GAME, STATE_PRE_GAME


@dataclass(frozen=True, slots=True)
class SeasonFilter:
    """Current season selection from shl.se."""

    season_uuid: str
    season_name: str
    series_uuid: str
    default_game_type_uuid: str
    ssgt_uuid: str
    # Game type code (e.g. "regular", "playoff") -> uuid
    game_types: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GameTeam:
    """One side of a game."""

    code: str | None  # None when not yet decided (e.g. playoff TBD)
    name: str | None
    logo: str | None
    score: int | None  # None before the game has started


@dataclass(frozen=True, slots=True)
class Game:
    """A single game."""

    uuid: str
    start: datetime  # timezone-aware, UTC
    state: str
    home: GameTeam
    away: GameTeam
    venue: str | None
    overtime: bool
    shootout: bool
    ssgt_uuid: str | None
    round_number: int | None
    round_label: str | None
    game_type: str | None = None  # "regular", "playoff", ... set by the coordinator

    @property
    def is_played(self) -> bool:
        """Return True if the game is finished."""
        return self.state == STATE_POST_GAME

    @property
    def is_upcoming(self) -> bool:
        """Return True if the game has not started."""
        return self.state == STATE_PRE_GAME

    @property
    def is_ongoing(self) -> bool:
        """Return True if the game is neither upcoming nor finished."""
        return not self.is_played and not self.is_upcoming

    def involves(self, team_code: str) -> bool:
        """Return True if the given team plays in this game."""
        return team_code in (self.home.code, self.away.code)


@dataclass(frozen=True, slots=True)
class Standing:
    """A team's row in the standings table."""

    rank: int
    team_code: str
    name: str
    logo: str | None
    games_played: int
    wins: int  # regulation wins
    overtime_wins: int
    losses: int  # regulation losses
    overtime_losses: int
    goals_for: int
    goals_against: int
    points: int

    @property
    def goal_difference(self) -> int:
        """Return goals for minus goals against."""
        return self.goals_for - self.goals_against
