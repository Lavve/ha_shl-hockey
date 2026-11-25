"""Config flow and options flow for SHL Hockey."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import ShlApiClient, ShlApiError
from .const import CONF_LIVE, CONF_TEAMS, DOMAIN
from .coordinator import ShlConfigEntry
from .models import Standing

_LOGGER = logging.getLogger(__name__)


class ShlConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._teams: list[SelectOptionDict] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick favorite teams."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get(CONF_TEAMS):
                return self.async_create_entry(
                    title="SHL Hockey",
                    data={},
                    options={CONF_TEAMS: user_input[CONF_TEAMS]},
                )
            errors[CONF_TEAMS] = "no_teams"

        if not self._teams:
            try:
                self._teams = await self._async_fetch_teams()
            except ShlApiError as err:
                _LOGGER.debug("Could not fetch teams: %s", err)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_TEAMS): _team_selector(self._teams)}
            ),
            errors=errors,
        )

    async def _async_fetch_teams(self) -> list[SelectOptionDict]:
        """Fetch the team list from the current standings."""
        client = ShlApiClient(async_get_clientsession(self.hass))
        season = await client.async_get_filter()
        return _team_options(await client.async_get_standings(season.ssgt_uuid))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ShlConfigEntry) -> ShlOptionsFlow:
        """Return the options flow."""
        return ShlOptionsFlow()


class ShlOptionsFlow(OptionsFlowWithReload):
    """Change favorite teams and live updates. Reloads the entry on save."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options form."""
        errors: dict[str, str] = {}
        options = {CONF_LIVE: False, **self.config_entry.options}

        if user_input is not None:
            if user_input.get(CONF_TEAMS):
                return self.async_create_entry(data=user_input)
            errors[CONF_TEAMS] = "no_teams"
            options.update(user_input)

        # Reuse the coordinator's data instead of calling shl.se again.
        coordinator = getattr(self.config_entry, "runtime_data", None)
        standings = coordinator.data.standings if coordinator and coordinator.data else []
        teams = _team_options(standings) or [
            SelectOptionDict(value=code, label=code)
            for code in options.get(CONF_TEAMS, [])
        ]

        schema = vol.Schema(
            {
                vol.Required(CONF_TEAMS): _team_selector(teams),
                vol.Required(CONF_LIVE): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, options),
            errors=errors,
        )


def _team_options(standings: list[Standing]) -> list[SelectOptionDict]:
    """Build select options (code -> name), sorted by name."""
    return sorted(
        (SelectOptionDict(value=s.team_code, label=s.name) for s in standings),
        key=lambda o: o["label"],
    )


def _team_selector(teams: list[SelectOptionDict]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=teams, multiple=True, mode=SelectSelectorMode.LIST
        )
    )

