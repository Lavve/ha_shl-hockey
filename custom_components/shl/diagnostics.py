"""Diagnostics for the SHL Hockey integration.

shl.se is public and unauthenticated, so there is nothing to redact. What
helps when something misbehaves is what was last read, and when the
coordinator intends to read again.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import ShlConfigEntry
from .models import Game


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ShlConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data

    result: dict[str, Any] = {
        "options": dict(entry.options),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": repr(coordinator.last_exception)
            if coordinator.last_exception
            else None,
            "update_interval": str(coordinator.update_interval),
            **coordinator.diagnostics(),
        },
    }
    if data is None:
        return result

    result["season"] = asdict(data.season)
    result["season_finished"] = data.season_finished
    result["games"] = {
        "total": len(data.games),
        "played": sum(g.is_played for g in data.games),
        "states": sorted({g.state for g in data.games}),
        "types": sorted({g.game_type or "unknown" for g in data.games}),
    }
    result["favorites"] = {
        code: {
            "next_game": _game(
                next((g for g in data.games if g.involves(code) and not g.is_played), None)
            ),
            "last_game": _game(
                next(
                    (g for g in reversed(data.games) if g.involves(code) and g.is_played),
                    None,
                )
            ),
            "standing": next(
                (asdict(s) for s in data.standings if s.team_code == code), None
            ),
        }
        for code in coordinator.favorites
    }
    result["standings"] = [asdict(s) for s in data.standings]
    return result


def _game(game: Game | None) -> dict[str, Any] | None:
    return asdict(game) if game else None
