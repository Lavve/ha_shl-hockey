"""Constants for the SHL Hockey integration.

This module must not import Home Assistant, so the API client can be
tested on its own (see scripts/test_api.py).
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "shl"
VERSION: Final = "0.1.0"

# --- shl.se (unofficial API) ---------------------------------------------

BASE_URL: Final = "https://www.shl.se/api"
URL_FILTER: Final = f"{BASE_URL}/sports-v2/season-series-game-types-filter"
URL_GAME_SCHEDULE: Final = f"{BASE_URL}/sports-v2/game-schedule"
URL_STANDINGS: Final = f"{BASE_URL}/statistics-v2/stats-info/standings_standings"

STANDINGS_PROVIDER: Final = "statnet"
STANDINGS_COUNT: Final = 25

# Identify ourselves honestly so SHL can see what is calling them.
USER_AGENT: Final = f"HomeAssistant-SHLHockey/{VERSION}"
REQUEST_TIMEOUT: Final = 20  # seconds

# --- Game types (stable codes in the filter response) ---------------------

GAME_TYPE_REGULAR: Final = "regular"
GAME_TYPE_PLAYOFF: Final = "playoff"
GAME_TYPE_QUALDOWN: Final = "qualdown"
# Fetched in addition to the regular season once it is finished.
POST_SEASON_GAME_TYPES: Final = (GAME_TYPE_PLAYOFF, GAME_TYPE_QUALDOWN)

# --- Config entry options ---------------------------------------------------

CONF_TEAMS: Final = "teams"
CONF_LIVE_INTERVAL: Final = "live_interval"  # minutes
CONF_MATCHDAY_INTERVAL: Final = "matchday_interval"  # minutes
CONF_IDLE_INTERVAL: Final = "idle_interval"  # hours

DEFAULT_LIVE_INTERVAL: Final = 5
DEFAULT_MATCHDAY_INTERVAL: Final = 30
DEFAULT_IDLE_INTERVAL: Final = 8

MIN_INTERVAL_MINUTES: Final = 5  # hard floor, never poll more often

# --- Game states (as returned by game-schedule) ---------------------------
# Only "pre-game" and "post-game" have been observed. Anything else is
# treated as an ongoing game.

STATE_PRE_GAME: Final = "pre-game"
STATE_POST_GAME: Final = "post-game"
