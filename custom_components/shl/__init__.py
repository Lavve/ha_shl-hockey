"""The SHL Hockey (unofficial) integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ShlApiClient
from .const import CONF_LIVE, DOMAIN, LEAGUE_DEVICE_ID
from .coordinator import ShlConfigEntry, ShlCoordinator


def _platforms(entry: ShlConfigEntry) -> list[Platform]:
    """Return the platforms; goal events only with live updates on."""
    platforms = [Platform.CALENDAR, Platform.SENSOR]
    if entry.options.get(CONF_LIVE, False):
        platforms.append(Platform.EVENT)
    return platforms


async def async_setup_entry(hass: HomeAssistant, entry: ShlConfigEntry) -> bool:
    """Set up SHL Hockey from a config entry."""
    session = async_get_clientsession(hass)
    coordinator = ShlCoordinator(hass, entry, ShlApiClient(session), session)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    if coordinator.feed is not None:
        entry.async_on_unload(coordinator.feed.stop)
    _remove_unselected_teams(hass, entry, coordinator.favorites)
    _remove_goal_events_when_off(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, _platforms(entry))
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


def _remove_goal_events_when_off(hass: HomeAssistant, entry: ShlConfigEntry) -> None:
    """Remove the goal event entities when live updates are turned off."""
    if entry.options.get(CONF_LIVE, False):
        return
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.domain == Platform.EVENT:
            registry.async_remove(entity.entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: ShlConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, _platforms(entry))


async def async_remove_entry(hass: HomeAssistant, entry: ShlConfigEntry) -> None:
    """Remove stored data when the integration is deleted."""
    await ShlCoordinator.async_remove_store(hass)
