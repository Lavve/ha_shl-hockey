"""DataUpdateCoordinator for the SHL Hockey integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ShlApiClient, ShlApiError
from .const import CONF_TEAMS, DOMAIN, GAME_TYPE_REGULAR, POST_SEASON_GAME_TYPES
from .live import FOLLOW_AFTER, FOLLOW_BEFORE, LiveFeed, LiveStatus, LiveTracker
from .models import Game, SeasonFilter, Standing
from .schedule import (
    FAILURE_RETRY,
    HOLD_DATA,
    IDLE_INTERVAL,
    TABLE_BEHIND_MAX,
    TABLE_BEHIND_RETRY,
    is_season_finished,
    next_update_delay,
    should_refresh_filter,
    table_behind,
)
from .table import standings_from_games

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.season_filter"

type ShlConfigEntry = ConfigEntry[ShlCoordinator]


def goal_signal(entry_id: str) -> str:
    """Return the dispatcher signal goals are sent on."""
    return f"{DOMAIN}_{entry_id}_goal"


@dataclass(frozen=True, slots=True)
class ShlData:
    """Everything the entities need."""

    season: SeasonFilter
    games: list[Game]  # regular season, plus post-season when relevant
    standings: list[Standing]  # always the regular season table
    season_finished: bool  # all regular season games played
    standings_source: str = "official"  # or "calculated" while SHL's lags


class ShlCoordinator(DataUpdateCoordinator[ShlData]):
    """Fetch SHL data on an adaptive schedule."""

    config_entry: ShlConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ShlConfigEntry,
        client: ShlApiClient,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=IDLE_INTERVAL,  # replaced after each update
        )
        self._client = client
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._season: SeasonFilter | None = None
        self._season_fetched: datetime | None = None
        self._games_fetched: datetime | None = None
        self._holding = False  # keeping old data because shl.se failed
        self._standings_fetched: datetime | None = None
        self._standings_played_count: int | None = None
        self._table_behind: list[str] = []
        self._table_behind_since: datetime | None = None
        self._table_behind_played: int | None = None
        self._standings_source = "official"
        self.tracker = LiveTracker()
        # Teams with their live switch on. Filled in by the switches as they
        # restore their state, so the stream stays closed until one is on.
        self.live_teams: set[str] = set()
        self.feed = LiveFeed(
            session,
            self._handle_live_message,
            lambda coro: entry.async_create_background_task(
                hass, coro, f"{DOMAIN} live stream"
            ),
        )

    @staticmethod
    async def async_remove_store(hass: HomeAssistant) -> None:
        """Delete the stored season filter."""
        await Store(hass, STORAGE_VERSION, STORAGE_KEY).async_remove()

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

        try:
            season = await self._async_get_season(now, previous)
            regular, post_season = await self._async_get_games(season)
        except ShlApiError as err:
            return self._hold_or_fail(now, previous, err)
        if self._holding:
            _LOGGER.info("shl.se can be read again")
            self._holding = False
        self._games_fetched = now

        finished = is_season_finished(regular)
        games = sorted(regular + post_season, key=lambda g: g.start)
        standings = await self._async_get_standings(now, season, regular, games, previous)

        self._follow_live_games(now, games)

        self.update_interval = next_update_delay(now, games, self.favorites)
        if self._table_behind:
            self.update_interval = min(self.update_interval, TABLE_BEHIND_RETRY)
        _LOGGER.debug("Next update in %s", self.update_interval)

        return ShlData(
            season=season,
            games=games,
            standings=standings,
            season_finished=finished,
            standings_source=self._standings_source,
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
            raise

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
        regular = _tag(
            await self._client.async_get_games(
                season.season_uuid, season.series_uuid, regular_uuid
            ),
            GAME_TYPE_REGULAR,
        )
        post_season: list[Game] = []
        if is_season_finished(regular):
            for code in POST_SEASON_GAME_TYPES:
                if game_type_uuid := season.game_types.get(code):
                    post_season += _tag(
                        await self._client.async_get_games(
                            season.season_uuid, season.series_uuid, game_type_uuid
                        ),
                        code,
                    )
        return regular, post_season

    def _hold_or_fail(
        self, now: datetime, previous: ShlData | None, err: ShlApiError
    ) -> ShlData:
        """Keep the last data for a while when shl.se cannot be read."""
        if (
            previous is None
            or self._games_fetched is None
            or now - self._games_fetched > HOLD_DATA
        ):
            raise UpdateFailed(f"Could not fetch data from shl.se: {err}") from err
        # Warn once per outage; the retries are only logged at debug level.
        log = _LOGGER.debug if self._holding else _LOGGER.warning
        log(
            "Could not read shl.se, keeping data from %s: %s",
            dt_util.as_local(self._games_fetched).strftime("%Y-%m-%d %H:%M"),
            err,
        )
        self._holding = True
        self.update_interval = FAILURE_RETRY
        return previous

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
        if (
            previous
            and previous.standings
            and self._standings_fetched is not None
            and played == self._standings_played_count
            and now - self._standings_fetched < IDLE_INTERVAL
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
        self._check_table_behind(now, standings, regular, played)
        if self._table_behind:
            # Show the right table at once; the official one takes over
            # when it has caught up.
            self._standings_source = "calculated"
            return standings_from_games(regular, standings)
        self._standings_source = "official"
        return standings

    def _check_table_behind(
        self,
        now: datetime,
        standings: list[Standing],
        regular: list[Game],
        played: int,
    ) -> None:
        """Read the table again soon if it is missing finished games."""
        behind = table_behind(standings, regular)
        if not behind:
            if self._table_behind:
                _LOGGER.debug("The table has caught up")
            self._table_behind = []
            self._table_behind_since = None
            return
        # The time limit counts from when this game night's results came in.
        if self._table_behind_since is None or self._table_behind_played != played:
            self._table_behind_since = now
            self._table_behind_played = played
        if now - self._table_behind_since > TABLE_BEHIND_MAX:
            if self._table_behind:
                _LOGGER.warning(
                    "The table is still missing games for %s, giving up until "
                    "the next game", ", ".join(behind)
                )
            self._table_behind = []
            return
        _LOGGER.debug("The table is missing games for %s", ", ".join(behind))
        self._table_behind = behind
        # Forget the played count, so the next update reads the table again.
        self._standings_played_count = None

    def live_status(self, game: Game, team_code: str) -> LiveStatus | None:
        """Return the live status of a game, if the team has live on."""
        if team_code not in self.live_teams:
            return None
        return self.tracker.statuses.get(game.uuid)

    @callback
    def async_set_live(self, team_code: str, on: bool) -> None:
        """Turn live updates on or off for a team, without reloading."""
        if on:
            self.live_teams.add(team_code)
        else:
            self.live_teams.discard(team_code)
        if self.data is not None:
            self._follow_live_games(dt_util.utcnow(), self.data.games)
            self.async_update_listeners()

    def _follow_live_games(self, now: datetime, games: list[Game]) -> None:
        """Keep the live stream open while a team with live on is playing."""
        teams = self.live_teams & set(self.favorites)
        playing = [
            g
            for g in games
            if not g.is_played
            and (g.home.code in teams or g.away.code in teams)
            and g.start - FOLLOW_BEFORE <= now < g.start + FOLLOW_AFTER
        ]
        for game in playing:
            self.tracker.expect(game.uuid, game.home.code, game.away.code)
        uuids = {g.uuid for g in playing}
        self.tracker.forget(uuids)
        self.feed.follow(uuids)

    @callback
    def _handle_live_message(self, kind: str, body: dict[str, Any]) -> None:
        """Apply a stream message and tell the entities."""
        changes = self.tracker.handle(kind, body)
        for goal in changes.goals:
            _LOGGER.debug("Goal: %s", goal)
            async_dispatcher_send(self.hass, goal_signal(self.config_entry.entry_id), goal)
        if changes.status is not None or changes.goals:
            self.async_update_listeners()
        if changes.ended:
            # Fetch the final result now instead of at the next poll.
            self.hass.async_create_task(self.async_request_refresh())

    def diagnostics(self) -> dict[str, Any]:
        """Return the coordinator's internal state for diagnostics."""

        def iso(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        return {
            "season_fetched": iso(self._season_fetched),
            "games_fetched": iso(self._games_fetched),
            "standings_fetched": iso(self._standings_fetched),
            "holding_old_data": self._holding,
            "table_behind": self._table_behind,
            "standings_source": self._standings_source,
            "live": {
                "teams": sorted(self.live_teams),
                "connected": self.feed.connected,
                "following": sorted(self.feed.following),
                "statuses": {
                    uuid: {
                        "home_score": s.home_score,
                        "away_score": s.away_score,
                        "state": s.state,
                        "period": s.period,
                        "clock": s.clock,
                        "updated": s.updated.isoformat(),
                    }
                    for uuid, s in self.tracker.statuses.items()
                },
                "recent_messages": list(self.feed.recent),
            },
            "table_behind_since": iso(self._table_behind_since),
        }


def _tag(games: list[Game], game_type: str) -> list[Game]:
    """Set the game type on each game."""
    return [replace(g, game_type=game_type) for g in games]
