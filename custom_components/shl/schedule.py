"""Decide when to fetch data from shl.se.

Pure functions without Home Assistant imports, so the rules can be
tested on their own (see scripts/test_schedule.py).

Polling rules, based on the user's favorite teams:
- A favorite team's game is in progress  -> every 5 minutes
- A favorite team plays within 6 hours   -> every 30 minutes
- Otherwise                              -> every 8 hours
Never more often than every 5 minutes.

The intervals are deliberately not user-configurable: being gentle with
shl.se is our responsibility, not the user's.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from .models import Game, Standing

LIVE_INTERVAL = timedelta(minutes=5)
MATCHDAY_INTERVAL = timedelta(minutes=30)
IDLE_INTERVAL = timedelta(hours=8)
# Hard floor: never poll more often than this.
MIN_INTERVAL = timedelta(minutes=5)

# How long before puck drop "matchday" polling starts.
MATCHDAY_WINDOW = timedelta(hours=6)
# A game that should have started but still says "pre-game" is treated as
# in progress for this long. Covers delays in SHL updating the state.
GAME_MAX_DURATION = timedelta(hours=4)

# How often to re-check the current season / game types.
FILTER_REFRESH = timedelta(days=7)
FILTER_REFRESH_SEASON_END = timedelta(days=1)

# SHL enters a result at the final whistle but publishes the updated table a
# while later, so a table read right after a game can still be missing it.
# Until it counts every played game it is read again at this pace - but not
# forever, in case the table and the schedule simply disagree.
TABLE_BEHIND_RETRY = timedelta(minutes=10)
TABLE_BEHIND_MAX = timedelta(hours=6)

# When shl.se cannot be read, the last data is kept this long (and reading
# retried at this pace) before the entities go unavailable. One failed read
# says nothing about the season already in hand.
HOLD_DATA = timedelta(days=1)
FAILURE_RETRY = timedelta(minutes=15)


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
) -> timedelta:
    """Return how long to wait until the next fetch."""
    teams = set(favorites)
    relevant = [g for g in games if g.home.code in teams or g.away.code in teams]

    if any(is_in_progress(g, now) for g in relevant):
        return _clamp(LIVE_INTERVAL)

    upcoming = [g for g in relevant if not g.is_played and g.start > now]
    if not upcoming:
        return _clamp(IDLE_INTERVAL)

    until_start = min(g.start for g in upcoming) - now
    if until_start <= MATCHDAY_WINDOW:
        # Poll on matchday, and make sure we wake up at puck drop.
        return _clamp(min(MATCHDAY_INTERVAL, until_start))

    # Sleep, but wake up when the matchday window opens.
    return _clamp(min(IDLE_INTERVAL, until_start - MATCHDAY_WINDOW))


def is_season_finished(regular_games: Sequence[Game]) -> bool:
    """Return True if every regular season game has been played."""
    return bool(regular_games) and all(g.is_played for g in regular_games)


def table_behind(
    standings: Sequence[Standing], regular_games: Sequence[Game]
) -> list[str]:
    """Return the team codes whose table row is missing played games.

    Teams that are not in the table at all are ignored, so a code that
    differs between the two endpoints cannot keep us polling.
    """
    played: dict[str, int] = {}
    for game in regular_games:
        if game.is_played:
            for code in (game.home.code, game.away.code):
                if code:
                    played[code] = played.get(code, 0) + 1
    rows = {row.team_code: row.games_played for row in standings}
    return sorted(
        code for code, count in played.items() if code in rows and rows[code] < count
    )


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
