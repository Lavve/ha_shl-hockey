"""Shared device info for the SHL entities."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN, LEAGUE_DEVICE_ID, SHL_URL
from .coordinator import ShlData


def team_device_info(data: ShlData | None, team_code: str) -> DeviceInfo:
    """Return the device for a favorite team."""
    return DeviceInfo(
        identifiers={(DOMAIN, team_code)},
        name=_team_name(data, team_code),
        manufacturer="SHL",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=SHL_URL,
    )


def league_device_info() -> DeviceInfo:
    """Return the device for the league itself."""
    return DeviceInfo(
        identifiers={(DOMAIN, LEAGUE_DEVICE_ID)},
        name="SHL",
        manufacturer="SHL",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=SHL_URL,
    )


def _team_name(data: ShlData | None, code: str) -> str:
    if data:
        for row in data.standings:
            if row.team_code == code:
                return row.name
    return code
