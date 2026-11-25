"""Check how live.py turns stream messages into status and goals (no network).

Usage:
    python scripts/test_live.py

The message shapes are what we expect from the stream; the first real game
will tell if they hold.
"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

PKG_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "shl"
pkg = types.ModuleType("shl")
pkg.__path__ = [str(PKG_DIR)]
sys.modules["shl"] = pkg
live = importlib.import_module("shl.live")

GAME = "g1"


def update(home: int, away: int, state: str = "Ongoing", period: int = 1,
           clock: str = "05:00", game: str = GAME) -> tuple[str, dict]:
    return live.KIND_GAME, {
        "gameUuid": game,
        "homeGoals": home,
        "awayGoals": away,
        "state": state,
        "time": {"period": period, "periodTime": clock},
        "homeTeam": {"teamCode": "OHK"},
        "awayTeam": {"teamCode": "FHC"},
    }


def goal(home: int, away: int, team: str, scorer: str = "Player",
         game: str = GAME) -> tuple[str, dict]:
    return live.KIND_GOAL, {
        "gameUuid": game,
        "type": "goal",
        "homeTeamValue": home,
        "awayTeamValue": away,
        "teamDetails": {"teamCode": team},
        "scorer": scorer,
        "playerNumber": 17,
        "period": 2,
        "time": "12:34",
        "goalStatus": "PP1",
        "assist": [{"firstName": "A", "lastName": "B", "playerNumber": 9}, "C D"],
    }


def run(messages, tracker=None):
    tracker = tracker or live.LiveTracker()
    tracker.expect(GAME, "OHK", "FHC")
    goals, ended = [], False
    for kind, body in messages:
        changes = tracker.handle(kind, body)
        goals += changes.goals
        ended = ended or changes.ended
    return tracker, goals, ended


def main() -> None:
    checks = []

    # A normal game: start, a home goal, an away goal with detail first.
    t, goals, ended = run([
        update(0, 0),
        update(1, 0),
        goal(1, 1, "FHC", "Frölunda Player"),
        update(1, 1, "PeriodBreak", 2, "20:00"),
        update(1, 1, "GameEnded", 3, "20:00"),
    ])
    checks += [
        ("Two goals announced", [(g.home_score, g.away_score) for g in goals], [(1, 0), (1, 1)]),
        ("Home goal belongs to OHK", goals[0].team_code, "OHK"),
        ("Away goal belongs to FHC, with scorer", (goals[1].team_code, goals[1].scorer),
         ("FHC", "#17 Frölunda Player")),
        ("Assists read from dicts and strings", goals[1].assists, ("#9 A B", "C D")),
        ("Strength and clock", (goals[1].strength, goals[1].clock), ("PP1", "12:34")),
        ("Phase mapped to our key", t.statuses[GAME].state, "ended"),
        ("Game end reported", ended, True),
    ]

    # Reconnect / restart mid-game: the replay must announce nothing.
    t, goals, _ = run([update(2, 1), goal(1, 0, "OHK"), goal(2, 0, "OHK"), goal(2, 1, "FHC")])
    checks.append(("Replay after connect announces nothing", goals, []))

    # The same goal seen twice (goal message, then a replay of it).
    t, goals, _ = run([update(0, 0), goal(1, 0, "OHK"), update(1, 0), goal(1, 0, "OHK")])
    checks.append(("Same goal only once", len(goals), 1))

    # A goal message before the game update that counts it raises the score.
    t, goals, _ = run([update(0, 0), goal(0, 1, "FHC")])
    checks.append(("Goal first updates the score",
                   (t.statuses[GAME].home_score, t.statuses[GAME].away_score), (0, 1)))

    # Disallowed goal: score goes down, the next real goal is announced again.
    t, goals, _ = run([update(0, 0), update(1, 0), update(0, 0), update(1, 0)])
    checks.append(("Disallowed goal, then a new one", len(goals), 2))

    # Two goals in one update.
    t, goals, _ = run([update(0, 0), update(2, 1)])
    checks.append(("Three goals in one update",
                   [g.team_code for g in goals], ["OHK", "OHK", "FHC"]))

    # Stream writes a different code: our schedule's code still wins.
    t, goals, _ = run([update(0, 0), goal(0, 1, "FROLUNDA")])
    checks.append(("Unknown stream code resolved by score", goals[0].team_code, "FHC"))

    # Messages for other games are kept apart.
    t, goals, _ = run([update(0, 0), update(0, 0, game="g2"), update(1, 0, game="g2")])
    checks.append(("Other game's goal not in this game", [g.game_uuid for g in goals], ["g2"]))

    # Parsing the stream's data lines.
    checks += [
        ("Split one event", [k for k, _ in live.split_messages(
            '{"gameOverview": {"gameUuid": "x"}, "other": {}}')], ["gameOverview"]),
        ("Ignore non-JSON", live.split_messages("ping"), []),
    ]

    failed = 0
    for name, got, expected in checks:
        ok = got == expected
        failed += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name:<44} {got!s:.60} (expected {expected!s:.60})")
    print(f"\n{'All passed' if not failed else f'{failed} failed'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
