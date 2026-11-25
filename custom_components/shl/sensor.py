"""Sensors for SHL Hockey.

Per favorite team (one device per team):
- next_game  (timestamp)  next or ongoing game
- last_game  (enum)       result of the last played game
- position   (int)        position in the standings
- games      (int)        games played; all of the season's games in attributes
                          (disabled by default)

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
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import ShlConfigEntry, ShlCoordinator, ShlData
from .live import LiveStatus
from .entity import league_device_info, team_device_info
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
    games: list[Game]
    next_game: Game | None
    live: LiveStatus | None
    last_game: Game | None
    standing: Standing | None

    @classmethod
    def build(cls, coordinator: ShlCoordinator, code: str) -> TeamView:
        """Build the view for a team."""
        data: ShlData = coordinator.data
        games = [g for g in data.games if g.involves(code)]
        next_game = next((g for g in games if not g.is_played), None)
        return cls(
            code=code,
            games=games,
            next_game=next_game,
            live=coordinator.live_status(next_game.uuid) if next_game else None,
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
    attrs: dict[str, Any] = {"status": status, **_game_attrs(game, view.code)}
    if (live := view.live) is not None:
        # Only with live updates on, while the game is followed.
        attrs.update(
            {
                "status": "in_progress",
                "home_score": live.home_score,
                "away_score": live.away_score,
                "live_state": live.state,
                "period": live.period,
                "clock": live.clock,
            }
        )
    return attrs


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
    return _game_result(game, view.code)


def _game_result(game: Game, code: str) -> str | None:
    """Return a played game's result from the team's point of view."""
    if not game.is_played:
        return None
    us, them = _sides(game, code)
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


def _games_attrs(view: TeamView) -> dict[str, Any]:
    """All of the season's games, played and upcoming, oldest first."""
    return {
        "games": [
            {
                "start": g.start,
                "game_type": g.game_type,
                "played": g.is_played,
                "result": _game_result(g, view.code),
                "home_game": g.home.code == view.code,
                "home_code": g.home.code,
                "away_code": g.away.code,
                "home_team": g.home.name,
                "away_team": g.away.name,
                "home_logo": g.home.logo,
                "away_logo": g.away.logo,
                "home_score": g.home.score,
                "away_score": g.away.score,
                "venue": g.venue,
            }
            for g in view.games
        ]
    }


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
    ShlTeamSensorDescription(
        key="games",
        translation_key="games",
        # Large attribute, mainly for custom cards: opt-in.
        entity_registry_enabled_default=False,
        value_fn=lambda v: sum(g.is_played for g in v.games),
        attrs_fn=_games_attrs,
        picture_fn=lambda v: None,
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
    # The game list is large; keep it out of the database.
    _unrecorded_attributes = frozenset({"games"})
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
        self._attr_device_info = team_device_info(coordinator.data, team_code)

    @property
    def _view(self) -> TeamView:
        return TeamView.build(self.coordinator, self._team_code)

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
        self._attr_device_info = league_device_info()

    @property
    def native_value(self) -> str:
        """Return the season name, e.g. 2026/2027."""
        return self.coordinator.data.season.season_name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the table."""
        return {
            "source": self.coordinator.data.standings_source,
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

