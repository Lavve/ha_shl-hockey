"""Manual test of the SHL API client against shl.se (outside Home Assistant).

Usage:
    pip install aiohttp
    python scripts/test_api.py            # overview
    python scripts/test_api.py FHC        # games for one team

Makes three requests to shl.se: filter, schedule and standings.
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
import sys
import types

import aiohttp

# Load custom_components/shl/{const,models,api}.py without running
# __init__.py (which needs Home Assistant).
PKG_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "shl"
pkg = types.ModuleType("shl")
pkg.__path__ = [str(PKG_DIR)]
sys.modules["shl"] = pkg
api = importlib.import_module("shl.api")
const = importlib.import_module("shl.const")


async def main(team: str | None) -> None:
    async with aiohttp.ClientSession() as session:
        client = api.ShlApiClient(session)

        flt = await client.async_get_filter()
        print(f"Season:      {flt.season_name} ({flt.season_uuid})")
        print(f"Series:      {flt.series_uuid}")
        print(f"Default GT:  {flt.default_game_type_uuid}")
        print(f"ssgtUuid:    {flt.ssgt_uuid}")
        print(f"Game types:  {flt.game_types}")

        regular = flt.game_types.get(const.GAME_TYPE_REGULAR, flt.default_game_type_uuid)
        games = await client.async_get_games(flt.season_uuid, flt.series_uuid, regular)
        if team:
            games = [g for g in games if g.involves(team.upper())]

        played = [g for g in games if g.is_played]
        upcoming = [g for g in games if g.is_upcoming]
        ongoing = [g for g in games if g.is_ongoing]
        states = sorted({g.state for g in games})
        print(f"\nGames: {len(games)} (played {len(played)}, upcoming "
              f"{len(upcoming)}, ongoing {len(ongoing)}) states={states}")

        def line(g) -> str:
            score = (f"{g.home.score}-{g.away.score}"
                     if g.home.score is not None else "  -  ")
            extra = " OT" if g.overtime else " SO" if g.shootout else ""
            return (f"  {g.start.astimezone():%Y-%m-%d %H:%M}  "
                    f"{g.home.code or 'TBD':>5} {score:^7} {g.away.code or 'TBD':<5}"
                    f"{extra}  {g.venue or ''}")

        print("\nLast 3 played:")
        for g in played[-3:]:
            print(line(g))
        print("\nNext 5:")
        for g in upcoming[:5]:
            print(line(g))

        table = await client.async_get_standings(flt.ssgt_uuid)
        print(f"\nStandings ({len(table)} teams):")
        print("   #  Team   GP   W OTW OTL   L   GF  GA  +/-  P")
        for r in table:
            print(f"  {r.rank:>2}  {r.team_code:<5} {r.games_played:>3} {r.wins:>3} "
                  f"{r.overtime_wins:>3} {r.overtime_losses:>3} {r.losses:>3} "
                  f"{r.goals_for:>4} {r.goals_against:>3} {r.goal_difference:>4} "
                  f"{r.points:>2}  {r.name}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
