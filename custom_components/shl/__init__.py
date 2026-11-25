"""The SHL (unofficial) integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ShlApiClient
from .const import DOMAIN, LEAGUE_DEVICE_ID
from .coordinator import ShlConfigEntry, ShlCoordinator

PLATFORMS: list[Platform] = [
    Platform.CALENDAR,
    Platform.EVENT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ShlConfigEntry) -> bool:
    """Set up SHL from a config entry."""
    session = async_get_clientsession(hass)
    coordinator = ShlCoordinator(hass, entry, ShlApiClient(session), session)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.feed.stop)
    _remove_unselected_teams(hass, entry, coordinator.favorites)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _remove_unselected_teams(
    hass: HomeAssistant, entry: ShlConfigEntry, favorites: list[str]
) -> None:
    """Remove devices for teams that are no longer favorites."""
    keep = {(DOMAIN, code) for code in favorites} | {(DOMAIN, LEAGUE_DEVICE_ID)}
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not device.identifiers & keep:
            registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )


async def async_unload_entry(hass: HomeAssistant, entry: ShlConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ShlConfigEntry) -> None:
    """Remove stored data when the integration is deleted."""
    await ShlCoordinator.async_remove_store(hass)
