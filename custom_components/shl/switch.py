"""A live updates switch per favorite team.

Off by default. Live can be turned off for a single game - when watching it
on TV, where the stream is usually ahead of the picture, or at the arena -
without reloading the integration. The state survives restarts.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import ShlConfigEntry, ShlCoordinator
from .entity import team_device_info

PARALLEL_UPDATES = 0  # nothing is fetched here


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShlConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one live switch per favorite team."""
    coordinator = entry.runtime_data
    async_add_entities(ShlLiveSwitch(coordinator, code) for code in coordinator.favorites)


class ShlLiveSwitch(SwitchEntity, RestoreEntity):
    """Turns live updates on or off for a team."""

    _attr_has_entity_name = True
    _attr_translation_key = "live_updates"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, coordinator: ShlCoordinator, team_code: str) -> None:
        """Initialize the switch."""
        self._coordinator = coordinator
        self._team_code = team_code
        self._attr_unique_id = f"{team_code}_live_updates".lower()
        self._attr_device_info = team_device_info(coordinator.data, team_code)
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore the last state."""
        if (last := await self.async_get_last_state()) is not None:
            self._attr_is_on = last.state == STATE_ON
        self._coordinator.async_set_live(self._team_code, self._attr_is_on)

    async def async_will_remove_from_hass(self) -> None:
        """Stop following the team's games when the switch goes away."""
        self._coordinator.async_set_live(self._team_code, False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn live updates on."""
        self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn live updates off."""
        self._set(False)

    def _set(self, on: bool) -> None:
        self._attr_is_on = on
        self._coordinator.async_set_live(self._team_code, on)
        self.async_write_ha_state()
