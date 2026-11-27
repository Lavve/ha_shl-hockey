"""A goal event per favorite team, from the live stream.

Fires only while the team's live switch is on: "goal_for" when the team
scores and "goal_against" when the opponent does - the trigger for a goal
light, a horn or a notification.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ShlConfigEntry, ShlCoordinator, goal_signal
from .entity import team_device_info
from .live import GoalScored

PARALLEL_UPDATES = 0  # nothing is fetched here

EVENT_GOAL_FOR = "goal_for"
EVENT_GOAL_AGAINST = "goal_against"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShlConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one goal event per favorite team."""
    coordinator = entry.runtime_data
    async_add_entities(ShlGoalEvent(coordinator, code) for code in coordinator.favorites)


class ShlGoalEvent(EventEntity):
    """Fires when the team, or its opponent, scores."""

    _attr_has_entity_name = True
    _attr_translation_key = "goal"
    _attr_event_types = [EVENT_GOAL_FOR, EVENT_GOAL_AGAINST]
    _attr_should_poll = False

    def __init__(self, coordinator: ShlCoordinator, team_code: str) -> None:
        """Initialize the event entity."""
        self._coordinator = coordinator
        self._team_code = team_code
        self._attr_unique_id = f"{team_code}_goal".lower()
        self._attr_device_info = team_device_info(coordinator.data, team_code)

    async def async_added_to_hass(self) -> None:
        """Listen for goals."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                goal_signal(self._coordinator.config_entry.entry_id),
                self._handle_goal,
            )
        )

    @callback
    def _handle_goal(self, goal: GoalScored) -> None:
        """Fire for goals in this team's games."""
        game = next(
            (g for g in self._coordinator.data.games if g.uuid == goal.game_uuid), None
        )
        if (
            game is None
            or not game.involves(self._team_code)
            or self._team_code not in self._coordinator.live_teams
        ):
            return
        ours = goal.team_code == self._team_code
        scoring = game.home if goal.team_code == game.home.code else game.away
        data: dict[str, Any] = {
            "team": scoring.name,
            "home_team": game.home.name,
            "away_team": game.away.name,
            "home_score": goal.home_score,
            "away_score": goal.away_score,
            "scorer": goal.scorer,
            "assists": list(goal.assists),
            "period": goal.period,
            "clock": goal.clock,
            "strength": goal.strength,
        }
        self._trigger_event(EVENT_GOAL_FOR if ours else EVENT_GOAL_AGAINST, data)
        self.async_write_ha_state()
