"""DataUpdateCoordinator for the SHL Hockey integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ShlApiClient, ShlApiError
from .const import (
    CONF_IDLE_INTERVAL,
    CONF_LIVE_INTERVAL,
    CONF_MATCHDAY_INTERVAL,
    CONF_TEAMS,
    DEFAULT_IDLE_INTERVAL,
    DEFAULT_LIVE_INTERVAL,
    DEFAULT_MATCHDAY_INTERVAL,
    DOMAIN,
    GAME_TYPE_REGULAR,
    POST_SEASON_GAME_TYPES,
)
from .models import Game, SeasonFilter, Standing
from .schedule import (
    Intervals,
    is_season_finished,
    next_update_delay,
    should_refresh_filter,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.season_filter"

type ShlConfigEntry = ConfigEntry[ShlCoordinator]


@dataclass(frozen=True, slots=True)
class ShlData:
    """Everything the entities need."""

    season: SeasonFilter
    games: list[Game]  # regular season, plus post-season when relevant
    standings: list[Standing]  # always the regular season table
    season_finished: bool  # all regular season games played


class ShlCoordinator(DataUpdateCoordinator[ShlData]):
    """Fetch SHL data on an adaptive schedule."""

    config_entry: ShlConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ShlConfigEntry, client: ShlApiClient
    ) -> None:
        """Initialize the coordinator."""
        intervals = _intervals_from_options(entry)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=intervals.idle,  # replaced after each update
        )
        self._client = client
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._season: SeasonFilter | None = None
        self._season_fetched: datetime | None = None
        self._standings_fetched: datetime | None = None
        self._standings_played_count: int | None = None

    @property
    def favorites(self) -> list[str]:
        """Return the selected team codes."""
        return list(self.config_entry.options.get(CONF_TEAMS, []))

    async def _async_setup(self) -> None:
        """Load the last known season filter, used if shl.se is down."""
        stored = await self._store.async_load()
        if stored:
            try:
                self._season = SeasonFilter(**stored)
            except TypeError:
                _LOGGER.debug("Ignoring stored season filter in old format")

    async def _async_update_data(self) -> ShlData:
        """Fetch data and schedule the next update."""
        now = dt_util.utcnow()
        previous = self.data

        season = await self._async_get_season(now, previous)
        regular, post_season = await self._async_get_games(season)
        finished = is_season_finished(regular)
        games = sorted(regular + post_season, key=lambda g: g.start)
        standings = await self._async_get_standings(now, season, regular, games, previous)

        intervals = _intervals_from_options(self.config_entry)
        self.update_interval = next_update_delay(now, games, self.favorites, intervals)
        _LOGGER.debug("Next update in %s", self.update_interval)

        return ShlData(
            season=season,
            games=games,
            standings=standings,
            season_finished=finished,
        )

    async def _async_get_season(
        self, now: datetime, previous: ShlData | None
    ) -> SeasonFilter:
        """Return the season filter, refreshing it when due."""
        finished = previous.season_finished if previous else False
        if self._season and not should_refresh_filter(
            now, self._season_fetched, finished
        ):
            return self._season

        try:
            season = await self._client.async_get_filter()
        except ShlApiError as err:
            if self._season:
                _LOGGER.warning("Using last known season, update failed: %s", err)
                return self._season
            raise UpdateFailed(f"Could not fetch season: {err}") from err

        if self._season and season.season_uuid != self._season.season_uuid:
            _LOGGER.info("New season detected: %s", season.season_name)
            self._standings_fetched = None  # force a new table

        self._season = season
        self._season_fetched = now
        await self._store.async_save(asdict(season))
        return season

    async def _async_get_games(
        self, season: SeasonFilter
    ) -> tuple[list[Game], list[Game]]:
        """Return (regular season games, post-season games)."""
        regular_uuid = season.game_types.get(
            GAME_TYPE_REGULAR, season.default_game_type_uuid
        )
        try:
            regular = await self._client.async_get_games(
                season.season_uuid, season.series_uuid, regular_uuid
            )
            post_season: list[Game] = []
            if is_season_finished(regular):
                for code in POST_SEASON_GAME_TYPES:
                    if game_type_uuid := season.game_types.get(code):
                        post_season += await self._client.async_get_games(
                            season.season_uuid, season.series_uuid, game_type_uuid
                        )
        except ShlApiError as err:
            raise UpdateFailed(f"Could not fetch games: {err}") from err
        return regular, post_season

    async def _async_get_standings(
        self,
        now: datetime,
        season: SeasonFilter,
        regular: list[Game],
        games: list[Game],
        previous: ShlData | None,
    ) -> list[Standing]:
        """Return the standings, only fetching when something has changed.

        The table only changes when a game finishes, so we skip the request
        unless the number of played games changed or the data is getting old.
        """
        played = sum(g.is_played for g in games)
        intervals = _intervals_from_options(self.config_entry)
        if (
            previous
            and previous.standings
            and self._standings_fetched is not None
            and played == self._standings_played_count
            and now - self._standings_fetched < intervals.idle
        ):
            return previous.standings

        # Always use the regular season table, also during playoffs.
        ssgt_uuid = next(
            (g.ssgt_uuid for g in regular if g.ssgt_uuid), season.ssgt_uuid
        )
        try:
            standings = await self._client.async_get_standings(ssgt_uuid)
        except ShlApiError as err:
            if previous and previous.standings:
                _LOGGER.warning("Keeping last standings, update failed: %s", err)
                return previous.standings
            _LOGGER.warning("Could not fetch standings: %s", err)
            return []

        if not standings and previous and previous.standings:
            return previous.standings

        self._standings_fetched = now
        self._standings_played_count = played
        return standings


def _intervals_from_options(entry: ConfigEntry) -> Intervals:
    options = entry.options
    return Intervals(
        live=timedelta(
            minutes=options.get(CONF_LIVE_INTERVAL, DEFAULT_LIVE_INTERVAL)
        ),
        matchday=timedelta(
            minutes=options.get(CONF_MATCHDAY_INTERVAL, DEFAULT_MATCHDAY_INTERVAL)
        ),
        idle=timedelta(hours=options.get(CONF_IDLE_INTERVAL, DEFAULT_IDLE_INTERVAL)),
    )
