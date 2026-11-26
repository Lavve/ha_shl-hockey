"""Check how live.py turns stream messages into status and goals (no network).

Usage:
    python scripts/test_live.py

The message shapes follow what the stream sent during FHC-IFB in November
2026: game updates about every 20 seconds, goal messages ahead of them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
         game: str = GAME, side: str | None = None) -> tuple[str, dict]:
    return live.KIND_GOAL, {
        "gameUuid": game,
        "type": "goal",
        "homeTeamValue": home,
        "awayTeamValue": away,
        "teamDetails": {"teamCode": team, **({"belongsTo": side} if side else {})},
        "scorer": scorer,
        "playerNumber": 17,
        "period": 2,
        "time": "12:34",
        "goalStatus": "PP1",
        "assist": [{"firstName": "A", "lastName": "B", "playerNumber": 9}, "C D"],
    }


START = datetime(2026, 11, 26, 18, 0, tzinfo=UTC)


def run(messages, tracker=None, every: int = 20):
    """Feed messages, one every `every` seconds, as the stream does."""
    tracker = tracker or live.LiveTracker()
    tracker.expect(GAME, "OHK", "FHC")
    goals, ended = [], False
    for i, (kind, body) in enumerate(messages):
        changes = tracker.handle(kind, body, START + timedelta(seconds=i * every))
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

    # Disallowed goal: the lower score lasts, so the next 1-0 is a new goal.
    t, goals, _ = run([update(0, 0), update(1, 0)] + [update(0, 0)] * 6 + [update(1, 0)])
    checks.append(("Disallowed goal, then a new one", len(goals), 2))

    # As in FHC-IFB: the goal message, then a game update still at 0-0, then
    # 1-0. One goal, and the score never drops back.
    t, goals, _ = run([update(0, 0), goal(1, 0, "OHK", side="home"), update(0, 0), update(1, 0)])
    checks += [
        ("Late game update: goal only once", len(goals), 1),
        ("Late game update: score kept", (t.statuses[GAME].home_score, t.statuses[GAME].away_score),
         (1, 0)),
    ]

    # The stream's code is not ours (Örebro is "ÖRE"); belongsTo decides,
    # even when the game update already counted the goal.
    t, goals, _ = run([update(0, 0), update(1, 0), goal(1, 0, "ÖRE", side="home")])
    checks.append(("belongsTo decides the team", goals[0].team_code, "OHK"))
    t, goals, _ = run([update(0, 0), goal(1, 0, "ÖRE", side="home")])
    checks.append(("belongsTo with a foreign code", goals[0].team_code, "OHK"))

    # Before puck drop the stream says NotStarted; that is no live status.
    t, goals, _ = run([update(0, 0, "NotStarted")])
    checks.append(("NotStarted gives no status", t.statuses.get(GAME), None))

    # Without our schedule's codes, the game update's teamId is used.
    t2 = live.LiveTracker()
    t2.handle(live.KIND_GAME, {"gameUuid": "x", "homeGoals": 0, "awayGoals": 0, "state": "Ongoing",
                               "homeTeam": {"teamId": "FHC", "teamCode": ""},
                               "awayTeam": {"teamId": "IFB", "teamCode": ""}})
    t2.handle(live.KIND_GAME, {"gameUuid": "x", "homeGoals": 0, "awayGoals": 1, "state": "Ongoing"})
    checks.append(("teamId when teamCode is empty", t2.handle(live.KIND_GAME, {
        "gameUuid": "x", "homeGoals": 1, "awayGoals": 1, "state": "Ongoing"}).goals[0].team_code, "FHC"))

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
