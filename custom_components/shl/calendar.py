"""A calendar of each favorite team's games.

Built from the games the coordinator already has, so it makes no requests
of its own. Its main use is the calendar trigger, which takes an offset:
"five minutes before puck drop" needs no template at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import ShlConfigEntry, ShlCoordinator
from .entity import team_device_info
from .models import Game

PARALLEL_UPDATES = 0  # coordinator based, no own requests

# Three 20-minute periods plus two intermissions: what SHL budgets for a
# broadcast slot. Only used for the event's end time.
GAME_DURATION = timedelta(hours=2, minutes=30)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShlConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one calendar per favorite team."""
    coordinator = entry.runtime_data
    async_add_entities(
        ShlTeamCalendar(coordinator, code) for code in coordinator.favorites
    )


class ShlTeamCalendar(CoordinatorEntity[ShlCoordinator], CalendarEntity):
    """A favorite team's games, played and upcoming."""

    _attr_has_entity_name = True
    _attr_translation_key = "games"

    def __init__(self, coordinator: ShlCoordinator, team_code: str) -> None:
        """Initialize the calendar."""
        super().__init__(coordinator)
        self._team_code = team_code
        self._attr_unique_id = f"{team_code}_calendar".lower()
        self._attr_device_info = team_device_info(coordinator.data, team_code)

    @property
    def _games(self) -> list[Game]:
        return [g for g in self.coordinator.data.games if g.involves(self._team_code)]

    @property
    def event(self) -> CalendarEvent | None:
        """Return the game in progress, or else the next one."""
        now = dt_util.utcnow()
        game = next(
            (g for g in self._games if not g.is_played and g.start + GAME_DURATION > now),
            None,
        )
        return _event(game) if game else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return the games between two points in time."""
        return [
            _event(g)
            for g in self._games
            if g.start < end_date and g.start + GAME_DURATION > start_date
        ]


def _event(game: Game) -> CalendarEvent:
    home = game.home.name or "?"
    away = game.away.name or "?"
    if game.is_played and game.home.score is not None and game.away.score is not None:
        extra = " (SO)" if game.shootout else " (OT)" if game.overtime else ""
        summary = f"{home} {game.home.score}–{game.away.score} {away}{extra}"
    else:
        summary = f"{home} – {away}"
    return CalendarEvent(
        start=game.start,
        end=game.start + GAME_DURATION,
        summary=summary,
        location=game.venue,
        uid=game.uuid,
    )
