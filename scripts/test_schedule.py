"""Check the polling rules in schedule.py with made-up games (no network).

Usage:
    python scripts/test_schedule.py
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib
from pathlib import Path
import sys
import types

# Load the package modules without running __init__.py (needs Home Assistant).
PKG_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "shl"
pkg = types.ModuleType("shl")
pkg.__path__ = [str(PKG_DIR)]
sys.modules["shl"] = pkg
models = importlib.import_module("shl.models")
schedule = importlib.import_module("shl.schedule")

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
FAV = ["FHC"]


def game(home: str, away: str, start: timedelta, state: str) -> models.Game:
    def team(code: str) -> models.GameTeam:
        return models.GameTeam(code=code, name=code, logo=None, score=None)

    return models.Game(
        uuid=f"{home}-{away}",
        start=NOW + start,
        state=state,
        home=team(home),
        away=team(away),
        venue=None,
        overtime=False,
        shootout=False,
        ssgt_uuid=None,
        round_number=None,
        round_label=None,
    )


H = timedelta(hours=1)
M = timedelta(minutes=1)

CASES: list[tuple[str, list, timedelta]] = [
    ("No games at all", [], 8 * H),
    ("Next game in 3 days", [game("FHC", "FBK", 72 * H, "pre-game")], 8 * H),
    ("Next game in 10 h -> wake when window opens", [game("FHC", "FBK", 10 * H, "pre-game")], 4 * H),
    ("Next game in 5 h (matchday)", [game("FHC", "FBK", 5 * H, "pre-game")], 30 * M),
    ("Next game in 12 min -> wake at puck drop", [game("FHC", "FBK", 12 * M, "pre-game")], 12 * M),
    ("Next game in 2 min -> 5 min floor", [game("FHC", "FBK", 2 * M, "pre-game")], 5 * M),
    ("Started 30 min ago, still pre-game", [game("FHC", "FBK", -30 * M, "pre-game")], 5 * M),
    ("Ongoing state", [game("FHC", "FBK", -1 * H, "live")], 5 * M),
    ("Finished 1 h ago, next in 3 days",
     [game("FHC", "FBK", -3 * H, "post-game"), game("FHC", "LHF", 72 * H, "pre-game")], 8 * H),
    ("Other teams playing now, not favorites", [game("LHF", "MIF", -30 * M, "pre-game")], 8 * H),
    ("Away game for favorite in 1 h", [game("OHK", "FHC", 1 * H, "pre-game")], 30 * M),
]


def main() -> None:
    failed = 0
    for name, games, expected in CASES:
        got = schedule.next_update_delay(NOW, games, FAV)
        ok = got == expected
        failed += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name:<48} {got!s:>9} (expected {expected})")

    # Filter refresh rules
    week, day = timedelta(days=7), timedelta(days=1)
    checks = [
        ("Filter: never fetched", schedule.should_refresh_filter(NOW, None, False), True),
        ("Filter: 3 days old, in season", schedule.should_refresh_filter(NOW, NOW - 3 * day, False), False),
        ("Filter: 7 days old, in season", schedule.should_refresh_filter(NOW, NOW - week, False), True),
        ("Filter: 1 day old, season over", schedule.should_refresh_filter(NOW, NOW - day, True), True),
        ("Season finished: no games", schedule.is_season_finished([]), False),
        ("Season finished: all played",
         schedule.is_season_finished([game("FHC", "FBK", -H, "post-game")]), True),
        ("Season finished: one left",
         schedule.is_season_finished([game("FHC", "FBK", -H, "post-game"),
                                      game("FHC", "LHF", H, "pre-game")]), False),
    ]
    for name, got, expected in checks:
        ok = got == expected
        failed += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name:<48} {got!s:>9} (expected {expected})")

    print(f"\n{'All passed' if not failed else f'{failed} failed'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
