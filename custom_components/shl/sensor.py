"""Sensors for SHL Hockey.

Per favorite team (one device per team):
- next_game  (timestamp)  next or ongoing game
- last_game  (enum)       result of the last played game
- position   (int)        position in the standings

League (one "SHL" device):
- standings               season name, full table in attributes

All values are raw (datetimes, ints, enum keys) so Home Assistant can
format and translate them for the user's language and locale.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, LEAGUE_DEVICE_ID, SHL_URL
from .coordinator import ShlConfigEntry, ShlCoordinator, ShlData
from .models import Game, GameTeam, Standing
from .schedule import is_in_progress

PARALLEL_UPDATES = 0  # coordinator based, no own requests

RESULT_OPTIONS = [
    "win",
    "loss",
    "overtime_win",
    "overtime_loss",
    "shootout_win",
    "shootout_loss",
]


@dataclass(frozen=True, slots=True)
class TeamView:
    """The coordinator data seen from one team."""

    code: str
    next_game: Game | None
    last_game: Game | None
    standing: Standing | None

    @classmethod
    def build(cls, data: ShlData, code: str) -> TeamView:
        """Build the view for a team."""
        games = [g for g in data.games if g.involves(code)]
        return cls(
            code=code,
            next_game=next((g for g in games if not g.is_played), None),
            last_game=next((g for g in reversed(games) if g.is_played), None),
            standing=next((s for s in data.standings if s.team_code == code), None),
        )


@dataclass(frozen=True, kw_only=True)
class ShlTeamSensorDescription(SensorEntityDescription):
    """Describes a per-team sensor."""

    value_fn: Callable[[TeamView], StateType | datetime]
    attrs_fn: Callable[[TeamView], dict[str, Any] | None]
    picture_fn: Callable[[TeamView], str | None]


def _next_game_attrs(view: TeamView) -> dict[str, Any] | None:
    if (game := view.next_game) is None:
        return None
    status = "in_progress" if is_in_progress(game, dt_util.utcnow()) else "upcoming"
    return {"status": status, **_game_attrs(game, view.code)}


def _last_game_attrs(view: TeamView) -> dict[str, Any] | None:
    if (game := view.last_game) is None:
        return None
    return {
        "start": game.start,
        **_game_attrs(game, view.code),
        "home_score": game.home.score,
        "away_score": game.away.score,
    }


def _game_attrs(game: Game, code: str) -> dict[str, Any]:
    home_game = game.home.code == code
    opponent = game.away if home_game else game.home
    return {
        "opponent": opponent.name,
        "opponent_logo": opponent.logo,
        "home_game": home_game,
        "venue": game.venue,
        "home_team": game.home.name,
        "away_team": game.away.name,
        "home_logo": game.home.logo,
        "away_logo": game.away.logo,
    }


def _result(view: TeamView) -> str | None:
    """Return the last game's result from the team's point of view."""
    if (game := view.last_game) is None:
        return None
    us, them = _sides(game, view.code)
    if us.score is None or them.score is None:
        return None
    outcome = "win" if us.score > them.score else "loss"
    if game.shootout:
        return f"shootout_{outcome}"
    if game.overtime:
        return f"overtime_{outcome}"
    return outcome


def _sides(game: Game, code: str) -> tuple[GameTeam, GameTeam]:
    return (game.home, game.away) if game.home.code == code else (game.away, game.home)


def _opponent_logo(game: Game | None, code: str) -> str | None:
    return _sides(game, code)[1].logo if game else None


def _position_attrs(view: TeamView) -> dict[str, Any] | None:
    if (s := view.standing) is None:
        return None
    return {
        "points": s.points,
        "games_played": s.games_played,
        "wins": s.wins,
        "overtime_wins": s.overtime_wins,
        "overtime_losses": s.overtime_losses,
        "losses": s.losses,
        "goals_for": s.goals_for,
        "goals_against": s.goals_against,
        "goal_difference": s.goal_difference,
    }


TEAM_SENSORS: tuple[ShlTeamSensorDescription, ...] = (
    ShlTeamSensorDescription(
        key="next_game",
        translation_key="next_game",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda v: v.next_game.start if v.next_game else None,
        attrs_fn=_next_game_attrs,
        picture_fn=lambda v: _opponent_logo(v.next_game, v.code),
    ),
    ShlTeamSensorDescription(
        key="last_game",
        translation_key="last_game",
        device_class=SensorDeviceClass.ENUM,
        options=RESULT_OPTIONS,
        value_fn=_result,
        attrs_fn=_last_game_attrs,
        picture_fn=lambda v: _opponent_logo(v.last_game, v.code),
    ),
    ShlTeamSensorDescription(
        key="position",
        translation_key="position",
        value_fn=lambda v: v.standing.rank if v.standing else None,
        attrs_fn=_position_attrs,
        picture_fn=lambda v: v.standing.logo if v.standing else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShlConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [ShlStandingsSensor(coordinator)]
    for code in coordinator.favorites:
        entities.extend(
            ShlTeamSensor(coordinator, code, description)
            for description in TEAM_SENSORS
        )
    async_add_entities(entities)


class ShlTeamSensor(CoordinatorEntity[ShlCoordinator], SensorEntity):
    """A sensor for one favorite team."""

    _attr_has_entity_name = True
    entity_description: ShlTeamSensorDescription

    def __init__(
        self,
        coordinator: ShlCoordinator,
        team_code: str,
        description: ShlTeamSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._team_code = team_code
        self._attr_unique_id = f"{team_code}_{description.key}".lower()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, team_code)},
            name=_team_name(coordinator.data, team_code),
            manufacturer="SHL",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=SHL_URL,
        )

    @property
    def _view(self) -> TeamView:
        return TeamView.build(self.coordinator.data, self._team_code)

    @property
    def native_value(self) -> StateType | datetime:
        """Return the state."""
        return self.entity_description.value_fn(self._view)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        return self.entity_description.attrs_fn(self._view)

    @property
    def entity_picture(self) -> str | None:
        """Return a logo, linked from shl.se (not bundled)."""
        return self.entity_description.picture_fn(self._view)


class ShlStandingsSensor(CoordinatorEntity[ShlCoordinator], SensorEntity):
    """The full standings table. State is the season name."""

    _attr_has_entity_name = True
    _attr_translation_key = "standings"
    # The table is large and changes rarely; keep it out of the database.
    _unrecorded_attributes = frozenset({"table"})

    def __init__(self, coordinator: ShlCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = "standings"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, LEAGUE_DEVICE_ID)},
            name="SHL",
            manufacturer="SHL",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=SHL_URL,
        )

    @property
    def native_value(self) -> str:
        """Return the season name, e.g. 2026/2027."""
        return self.coordinator.data.season.season_name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the table."""
        return {
            "table": [
                {
                    "rank": s.rank,
                    "team_code": s.team_code,
                    "name": s.name,
                    "logo": s.logo,
                    "points": s.points,
                    "games_played": s.games_played,
                    "wins": s.wins,
                    "overtime_wins": s.overtime_wins,
                    "overtime_losses": s.overtime_losses,
                    "losses": s.losses,
                    "goals_for": s.goals_for,
                    "goals_against": s.goals_against,
                    "goal_difference": s.goal_difference,
                }
                for s in self.coordinator.data.standings
            ]
        }


def _team_name(data: ShlData | None, code: str) -> str:
    if data:
        for s in data.standings:
            if s.team_code == code:
                return s.name
    return code
