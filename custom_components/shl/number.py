"""The live delay: one number for the whole integration.

Streaming, and sometimes TV, runs behind the live stream, so a goal light
could give the goal away before it is seen. Every live message - score,
clock, goal events - is held back by this many seconds. It sits on the SHL
device because one TV is watched at a time, and two favorite teams meeting
each other must not get two delays in the same game. Polling is unaffected.
"""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import LEAGUE_DEVICE_ID
from .coordinator import ShlConfigEntry, ShlCoordinator
from .entity import league_device_info

PARALLEL_UPDATES = 0  # nothing is fetched here

MAX_DELAY = 300


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ShlConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the live delay."""
    async_add_entities([ShlLiveDelay(entry.runtime_data)])


class ShlLiveDelay(RestoreNumber):
    """Seconds to hold live updates back."""

    _attr_has_entity_name = True
    _attr_translation_key = "live_delay"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = MAX_DELAY
    _attr_native_step = 5
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_mode = NumberMode.BOX
    _attr_should_poll = False

    def __init__(self, coordinator: ShlCoordinator) -> None:
        """Initialize the number."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{LEAGUE_DEVICE_ID}_live_delay"
        self._attr_device_info = league_device_info()
        self._attr_native_value = 0

    async def async_added_to_hass(self) -> None:
        """Restore the last value."""
        if (last := await self.async_get_last_number_data()) is not None and (
            last.native_value is not None
        ):
            self._attr_native_value = min(max(last.native_value, 0), MAX_DELAY)
        self._coordinator.live_delay = int(self._attr_native_value)

    async def async_set_native_value(self, value: float) -> None:
        """Change the delay; messages already waiting keep theirs."""
        self._attr_native_value = value
        self._coordinator.live_delay = int(value)
        self.async_write_ha_state()
