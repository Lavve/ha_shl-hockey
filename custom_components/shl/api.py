"""Client for the unofficial shl.se API.

Pure aiohttp, no Home Assistant imports. The client only fetches and
parses; deciding *when* to fetch is the coordinator's job.
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

import aiohttp

from .const import (
    REQUEST_TIMEOUT,
    STANDINGS_COUNT,
    STANDINGS_PROVIDER,
    URL_FILTER,
    URL_GAME_SCHEDULE,
    URL_STANDINGS,
    USER_AGENT,
)
from .models import Game, GameTeam, SeasonFilter, Standing

_LOGGER = logging.getLogger(__name__)


class ShlApiError(Exception):
    """Base error for the SHL API."""


class ShlApiConnectionError(ShlApiError):
    """Network problem or bad HTTP status."""


class ShlApiResponseError(ShlApiError):
    """The response did not have the expected format."""


class ShlApiClient:
    """Fetch and parse data from shl.se."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialize with a shared aiohttp session."""
        self._session = session

    async def async_get_filter(self) -> SeasonFilter:
        """Return the current season, series and game types."""
        data = await self._get_json(URL_FILTER)
        return _parse_filter(data)

    async def async_get_games(
        self, season_uuid: str, series_uuid: str, game_type_uuid: str
    ) -> list[Game]:
        """Return all games (played and unplayed), sorted by start time."""
        data = await self._get_json(
            URL_GAME_SCHEDULE,
            {
                "seasonUuid": season_uuid,
                "seriesUuid": series_uuid,
                "gameTypeUuid": game_type_uuid,
                "gamePlace": "all",
                "played": "all",
            },
        )
        return _parse_games(data)

    async def async_get_standings(self, ssgt_uuid: str) -> list[Standing]:
        """Return the standings table, sorted by rank."""
        data = await self._get_json(
            URL_STANDINGS,
            {
                "ssgtUuid": ssgt_uuid,
                "provider": STANDINGS_PROVIDER,
                "count": str(STANDINGS_COUNT),
            },
        )
        return _parse_standings(data)

    async def _get_json(self, url: str, params: dict[str, str] | None = None) -> Any:
        """GET a URL and return decoded JSON."""
        try:
            async with self._session.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    raise ShlApiConnectionError(
                        f"HTTP {resp.status} from {url}"
                    )
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ShlApiConnectionError(f"Error fetching {url}: {err}") from err
        except ValueError as err:  # invalid JSON
            raise ShlApiResponseError(f"Invalid JSON from {url}") from err


# --- Parsing ---------------------------------------------------------------
# Kept as module-level functions so they are easy to test without network.


def _parse_filter(data: Any) -> SeasonFilter:
    try:
        default = data["defaultSsgtFilter"]
        season_uuid = default["season"]
        seasons = {s["uuid"]: s for s in data.get("season", [])}
        game_types = {
            gt["code"]: gt["uuid"]
            for gt in data.get("gameType", [])
            if gt.get("code") and gt.get("uuid") and not gt.get("deleted")
        }
        return SeasonFilter(
            season_uuid=season_uuid,
            season_name=_pick_name(seasons.get(season_uuid, {}).get("names"))
            or season_uuid,
            series_uuid=default["series"],
            default_game_type_uuid=default["gameType"],
            ssgt_uuid=data["ssgtUuid"],
            game_types=game_types,
        )
    except (KeyError, TypeError) as err:
        raise ShlApiResponseError(f"Unexpected filter format: {err}") from err


def _parse_games(data: Any) -> list[Game]:
    raw_games = data.get("gameInfo") if isinstance(data, dict) else data
    if not isinstance(raw_games, list):
        raise ShlApiResponseError("Unexpected game-schedule format")

    games: list[Game] = []
    for raw in raw_games:
        try:
            games.append(
                Game(
                    uuid=raw["uuid"],
                    start=datetime.fromisoformat(raw["rawStartDateTime"]),
                    state=raw.get("state", ""),
                    home=_parse_game_team(raw.get("homeTeamInfo")),
                    away=_parse_game_team(raw.get("awayTeamInfo")),
                    venue=_parse_venue(raw.get("venueInfo")),
                    overtime=bool(raw.get("overtime")),
                    shootout=bool(raw.get("shootout")),
                    ssgt_uuid=raw.get("ssgtUuid"),
                    round_number=_to_int(raw.get("roundNumber")),
                    round_label=raw.get("roundLabel") or None,
                )
            )
        except (KeyError, TypeError, ValueError) as err:
            # One odd game should not break the whole schedule.
            _LOGGER.debug("Skipping game %s: %s", raw.get("uuid"), err)

    games.sort(key=lambda g: g.start)
    return games


def _parse_game_team(raw: dict[str, Any] | None) -> GameTeam:
    raw = raw or {}
    names = raw.get("names") or {}
    code = (raw.get("code") or "").strip() or None
    name = names.get("long") or names.get("full") or None
    decided = code is not None and name is not None
    return GameTeam(
        code=code if decided else None,
        name=name if decided else None,
        logo=(raw.get("icon") or None) if decided else None,
        score=_to_int(raw.get("score")),
    )


def _parse_venue(raw: dict[str, Any] | None) -> str | None:
    name = (raw or {}).get("name")
    return None if not name or name == "Unknown Arena" else name


def _parse_standings(data: Any) -> list[Standing]:
    root = data[0] if isinstance(data, list) and data else data
    if not isinstance(root, dict):
        raise ShlApiResponseError("Unexpected standings format")

    teams: dict[str, Any] = root.get("teams") or {}
    rows: list[Standing] = []
    for stat in root.get("stats") or []:
        try:
            code = stat["info"]["code"]
            team = teams.get(code) or stat["info"]
            names = team.get("teamNames") or {}
            rows.append(
                Standing(
                    rank=int(stat["Rank"]),
                    team_code=code,
                    name=names.get("long") or names.get("full") or code,
                    logo=_logo_url(team.get("logo")),
                    games_played=int(stat["GP"]),
                    # In standings_standings, W/L are regulation only.
                    wins=int(stat["W"]),
                    overtime_wins=int(stat.get("OTW", 0)),
                    losses=int(stat["L"]),
                    overtime_losses=int(stat.get("OTL", 0)),
                    goals_for=int(stat["G"]),
                    goals_against=int(stat["GA"]),
                    points=int(stat["Points"]),
                )
            )
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.debug("Skipping standings row: %s", err)

    rows.sort(key=lambda r: r.rank)
    return rows


# --- Helpers ---------------------------------------------------------------


def _pick_name(names: Any, language: str = "sv") -> str | None:
    """Pick a translation from [{language, translation}, ...]."""
    if not isinstance(names, list) or not names:
        return None
    for item in names:
        if item.get("language") == language and item.get("translation"):
            return item["translation"]
    return names[0].get("translation")


def _logo_url(value: Any) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        return value.get("url") or None
    return None


def _to_int(value: Any) -> int | None:
    """Convert to int; "N/A", "" and None become None."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
