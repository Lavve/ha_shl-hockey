"""The SHL Hockey (unofficial) integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ShlApiClient
from .coordinator import ShlConfigEntry, ShlCoordinator

# Sensors are added in the next step.
PLATFORMS: list[Platform] = []


async def async_setup_entry(hass: HomeAssistant, entry: ShlConfigEntry) -> bool:
    """Set up SHL Hockey from a config entry."""
    client = ShlApiClient(async_get_clientsession(hass))
    coordinator = ShlCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ShlConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ShlConfigEntry) -> None:
    """Remove stored data when the integration is deleted."""
    await ShlCoordinator.async_remove_store(hass)
