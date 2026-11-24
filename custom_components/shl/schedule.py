"""Decide when to fetch data from shl.se.

Pure functions without Home Assistant imports, so the rules can be
tested on their own (see scripts/test_schedule.py).

Polling rules, based on the user's favorite teams:
- A favorite team's game is in progress  -> live interval (default 5 min)
- A favorite team plays within 6 hours   -> matchday interval (default 30 min)
- Otherwise                              -> idle interval (default 8 h)
Never more often than every 5 minutes.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from .const import (
    DEFAULT_IDLE_INTERVAL,
    DEFAULT_LIVE_INTERVAL,
    DEFAULT_MATCHDAY_INTERVAL,
    MIN_INTERVAL_MINUTES,
)
from .models import Game

MIN_INTERVAL = timedelta(minutes=MIN_INTERVAL_MINUTES)

# How long before puck drop "matchday" polling starts.
MATCHDAY_WINDOW = timedelta(hours=6)
# A game that should have started but still says "pre-game" is treated as
# in progress for this long. Covers delays in SHL updating the state.
GAME_MAX_DURATION = timedelta(hours=4)

# How often to re-check the current season / game types.
FILTER_REFRESH = timedelta(days=7)
FILTER_REFRESH_SEASON_END = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class Intervals:
    """Polling intervals."""

    live: timedelta = timedelta(minutes=DEFAULT_LIVE_INTERVAL)
    matchday: timedelta = timedelta(minutes=DEFAULT_MATCHDAY_INTERVAL)
    idle: timedelta = timedelta(hours=DEFAULT_IDLE_INTERVAL)


def is_in_progress(game: Game, now: datetime) -> bool:
    """Return True if the game is (probably) being played right now."""
    if game.is_played:
        return False
    if game.is_ongoing:
        return True
    return game.start <= now < game.start + GAME_MAX_DURATION


def next_update_delay(
    now: datetime,
    games: Sequence[Game],
    favorites: Iterable[str],
    intervals: Intervals,
) -> timedelta:
    """Return how long to wait until the next fetch."""
    teams = set(favorites)
    relevant = [g for g in games if g.home.code in teams or g.away.code in teams]

    if any(is_in_progress(g, now) for g in relevant):
        return _clamp(intervals.live)

    upcoming = [g for g in relevant if not g.is_played and g.start > now]
    if not upcoming:
        return _clamp(intervals.idle)

    until_start = min(g.start for g in upcoming) - now
    if until_start <= MATCHDAY_WINDOW:
        # Poll on matchday, and make sure we wake up at puck drop.
        return _clamp(min(intervals.matchday, until_start))

    # Sleep, but wake up when the matchday window opens.
    return _clamp(min(intervals.idle, until_start - MATCHDAY_WINDOW))


def is_season_finished(regular_games: Sequence[Game]) -> bool:
    """Return True if every regular season game has been played."""
    return bool(regular_games) and all(g.is_played for g in regular_games)


def should_refresh_filter(
    now: datetime, last_fetched: datetime | None, season_finished: bool
) -> bool:
    """Return True if the season filter should be fetched again.

    Weekly during the season; daily once the regular season is over, so a
    switch to playoffs or a new season is picked up within a day.
    """
    if last_fetched is None:
        return True
    max_age = FILTER_REFRESH_SEASON_END if season_finished else FILTER_REFRESH
    return now - last_fetched >= max_age


def _clamp(delay: timedelta) -> timedelta:
    return max(delay, MIN_INTERVAL)
