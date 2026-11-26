"""Live score and goals from the stream shl.se's game center listens to.

The stream is Server-Sent Events: one connection that the server pushes
messages down as things happen, so following a game costs one request
rather than frequent polling. It is only opened while a favorite team is
playing, and closed again afterwards.

What we know about it, from the first game we followed (FHC-IFB, Nov 2026):
- Two message kinds matter. A game update carries the score, the phase of
  the game and the clock; a goal message carries the scorer and the score
  the goal made.
- Every game of the day is re-sent about every 20 seconds, and each goal
  message is repeated too, sometimes with an assist added later. Goals are
  only announced once per score.
- The goal message comes first; the game update can still show the old
  score for another 20 seconds. That is a late update, not a disallowed
  goal, so a lower score only counts once it has lasted (SCORE_LOWERED).
- The game update's team codes are empty (the code is in "teamId"), and the
  goal message's code is not always ours (Örebro is "ÖRE", not "OHK"), so
  the goal message's "belongsTo" (home/away) decides who scored.
- On connect the stream replays the day so far. We reconnect after a long
  silence.

No Home Assistant imports, so the message handling can be tested alone.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import logging
from typing import Any

import aiohttp

from .const import USER_AGENT

_LOGGER = logging.getLogger(__name__)

LIVE_STREAM_URL = "https://game-broadcaster.s8y.se/live/game"
# Follow a game from a little before puck drop until it is reported played,
# or at most this long after the start (overtime, shootout, a late result).
FOLLOW_BEFORE = timedelta(minutes=5)
FOLLOW_AFTER = timedelta(hours=4)
KIND_GAME = "gameOverview"
KIND_GOAL = "gameScorer"

# Reconnect when nothing has arrived for this long (seconds). A reconnect
# only costs a replay of the day so far.
SILENCE_LIMIT = 300
RETRY_FIRST = 5
RETRY_LONGEST = 120
# A score below one already announced counts as a disallowed goal only
# after this long; before that it is a game update that has not caught up.
SCORE_LOWERED = timedelta(seconds=90)

# The phases the stream reports, mapped to our own state keys.
PHASES = {
    "ongoing": "ongoing",
    "periodbreak": "period_break",
    "overtime": "overtime",
    "shootout": "shootout",
    "gameended": "ended",
}
PHASE_ENDED = "ended"


@dataclass(slots=True)
class LiveStatus:
    """A game as the stream last described it."""

    game_uuid: str
    home_score: int
    away_score: int
    state: str | None = None  # a value of PHASES, or the raw phase lowercased
    period: int | None = None
    clock: str | None = None
    updated: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def ended(self) -> bool:
        """Return True if the stream says the game is over."""
        return self.state == PHASE_ENDED


@dataclass(frozen=True, slots=True)
class GoalScored:
    """One goal, announced once."""

    game_uuid: str
    team_code: str | None  # the scoring team
    home_score: int
    away_score: int
    scorer: str | None = None
    assists: tuple[str, ...] = ()
    period: int | None = None
    clock: str | None = None
    strength: str | None = None  # e.g. EQ, PP1, SH1


@dataclass(slots=True)
class Changes:
    """What one message changed."""

    status: LiveStatus | None = None
    goals: list[GoalScored] = field(default_factory=list)
    ended: bool = False


class LiveTracker:
    """Turn stream messages into game status and goals.

    Keeps the latest status per game and remembers which scores have been
    announced, so a replay after a reconnect announces nothing twice.
    """

    def __init__(self) -> None:
        """Start with nothing known."""
        self.statuses: dict[str, LiveStatus] = {}
        self._home_codes: dict[str, str | None] = {}
        self._away_codes: dict[str, str | None] = {}
        self._announced: dict[str, set[tuple[int, int]]] = {}
        self._details: dict[str, dict[tuple[int, int], GoalScored]] = {}
        # When the stream first showed a score below the announced one.
        self._lowered_since: dict[str, datetime] = {}

    def expect(self, game_uuid: str, home_code: str | None, away_code: str | None) -> None:
        """Tell the tracker which teams play, as our schedule writes them."""
        self._home_codes[game_uuid] = home_code
        self._away_codes[game_uuid] = away_code

    def handle(
        self, kind: str, body: dict[str, Any], now: datetime | None = None
    ) -> Changes:
        """Apply one message and return what changed."""
        now = now or datetime.now(UTC)
        if kind == KIND_GAME:
            return self._game_update(body, now)
        if kind == KIND_GOAL:
            return self._goal_message(body, now)
        return Changes()

    def _game_update(self, body: dict[str, Any], now: datetime) -> Changes:
        uuid = str(body.get("gameUuid") or "")
        home_side = body.get("homeTeam") or {}
        away_side = body.get("awayTeam") or {}
        home = _number(body.get("homeGoals", home_side.get("score")))
        away = _number(body.get("awayGoals", away_side.get("score")))
        if not uuid or home is None or away is None:
            return Changes()
        if str(body.get("state") or "").lower() == "notstarted":
            return Changes()

        # Our schedule's codes win; the stream's are only a fallback.
        self._home_codes.setdefault(uuid, _team_code(home_side))
        self._away_codes.setdefault(uuid, _team_code(away_side))
        timing = body.get("time") or {}
        before = self.statuses.get(uuid)
        if before is not None and (home < before.home_score or away < before.away_score):
            since = self._lowered_since.setdefault(uuid, now)
            if now - since < SCORE_LOWERED:
                # Most likely a game update behind the goal message: keep the
                # higher score and take the rest of the update.
                home, away = before.home_score, before.away_score
        else:
            self._lowered_since.pop(uuid, None)
        status = LiveStatus(
            game_uuid=uuid,
            home_score=home,
            away_score=away,
            state=_phase(body.get("state")) or (before.state if before else None),
            period=_number(timing.get("period")) or (before.period if before else None),
            clock=timing.get("periodTime") or (before.clock if before else None),
            updated=now,
        )
        self.statuses[uuid] = status

        changes = Changes(status=status, ended=status.ended)
        announced = self._announced.get(uuid)
        if announced is None:
            # First sight of this game (start, restart or reconnect): take the
            # score as it is, without announcing goals scored before now.
            self._announced[uuid] = {
                (h, a) for h in range(home + 1) for a in range(away + 1)
            }
            return changes

        # A disallowed goal lowers the score; forget what was above it.
        announced -= {(h, a) for (h, a) in announced if h > home or a > away}
        if before is not None:
            changes.goals = self._goals_between(uuid, before, status)
        return changes

    def _goals_between(
        self, uuid: str, before: LiveStatus, after: LiveStatus
    ) -> list[GoalScored]:
        """Announce the goals that took the score from one status to another."""
        goals: list[GoalScored] = []
        home, away = before.home_score, before.away_score
        # One step at a time, home goals first: a single update rarely holds
        # more than one goal, and the exact order is unknown when it does.
        while home < after.home_score or away < after.away_score:
            if home < after.home_score:
                home += 1
                team = self._home_codes.get(uuid)
            else:
                away += 1
                team = self._away_codes.get(uuid)
            if goal := self._announce(uuid, home, away, team):
                goals.append(goal)
        return goals

    def _goal_message(self, body: dict[str, Any], now: datetime) -> Changes:
        uuid = str(body.get("gameUuid") or "")
        if not uuid or body.get("type") not in (None, "goal"):
            return Changes()
        home = _number(body.get("homeTeamValue"))
        away = _number(body.get("awayTeamValue"))
        if home is None or away is None:
            return Changes()
        team = self._scoring_team(uuid, body, home, away)
        detail = GoalScored(
            game_uuid=uuid,
            team_code=team,
            home_score=home,
            away_score=away,
            scorer=_player(body.get("scorer"), body.get("playerNumber")),
            assists=tuple(
                name for item in body.get("assist") or [] if (name := _assist_name(item))
            ),
            period=_number(body.get("period")),
            clock=body.get("time"),
            strength=body.get("goalStatus"),
        )
        self._details.setdefault(uuid, {})[(home, away)] = detail
        if uuid not in self._announced:
            # Part of the replay before we have seen the game itself.
            return Changes()

        changes = Changes()
        if goal := self._announce(uuid, home, away, team):
            changes.goals.append(goal)
            # A goal can arrive before the game update that counts it.
            status = self.statuses.get(uuid)
            if status and home + away > status.home_score + status.away_score:
                status.home_score, status.away_score = home, away
                status.updated = now
                changes.status = status
        return changes

    def _scoring_team(
        self, uuid: str, body: dict[str, Any], home: int, away: int
    ) -> str | None:
        """Return the scoring team as our schedule writes it."""
        home_code = self._home_codes.get(uuid)
        away_code = self._away_codes.get(uuid)
        details = body.get("teamDetails") or {}
        side = str(details.get("belongsTo") or "").lower()
        if side == "home":
            return home_code
        if side == "away":
            return away_code
        stream_code = details.get("teamCode")
        if stream_code in (home_code, away_code):
            return stream_code
        # Otherwise tell by which side's score went up.
        status = self.statuses.get(uuid)
        if status is not None:
            if home > status.home_score and away <= status.away_score:
                return home_code
            if away > status.away_score and home <= status.home_score:
                return away_code
        return stream_code

    def _announce(
        self, uuid: str, home: int, away: int, team: str | None
    ) -> GoalScored | None:
        """Return the goal for a score, unless it has been announced."""
        announced = self._announced.setdefault(uuid, set())
        if (home, away) in announced:
            return None
        announced.add((home, away))
        detail = self._details.get(uuid, {}).get((home, away))
        return detail or GoalScored(
            game_uuid=uuid, team_code=team, home_score=home, away_score=away
        )

    def forget(self, keep: set[str]) -> None:
        """Drop games that are no longer followed."""
        for store in (
            self.statuses,
            self._home_codes,
            self._away_codes,
            self._announced,
            self._details,
            self._lowered_since,
        ):
            for uuid in [u for u in store if u not in keep]:
                del store[uuid]


def split_messages(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Return (kind, body) pairs from one event's data."""
    try:
        message = json.loads(text)
    except ValueError:
        return []
    if not isinstance(message, dict):
        return []
    return [
        (kind, body)
        for kind, body in message.items()
        if kind in (KIND_GAME, KIND_GOAL) and isinstance(body, dict)
    ]


class LiveFeed:
    """Keep the stream open while there are games to follow."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        on_message: Callable[[str, dict[str, Any]], None],
        start_task: Callable[[Coroutine[Any, Any, None]], asyncio.Task[None]],
    ) -> None:
        """Initialize, without connecting."""
        self._session = session
        self._on_message = on_message
        self._start_task = start_task
        self._task: asyncio.Task[None] | None = None
        self.following: set[str] = set()
        self.connected = False
        self.recent: deque[str] = deque(maxlen=20)  # raw messages, for diagnostics

    def follow(self, game_uuids: set[str]) -> None:
        """Follow these games: connect if needed, disconnect if none."""
        self.following = set(game_uuids)
        if not self.following:
            self.stop()
        elif self._task is None or self._task.done():
            self._task = self._start_task(self._keep_connected())

    def stop(self) -> None:
        """Close the stream."""
        self.following = set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        self.connected = False

    async def _keep_connected(self) -> None:
        delay = RETRY_FIRST
        while self.following:
            try:
                await self._read_stream()
                delay = RETRY_FIRST  # the server closed it cleanly
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("Live stream lost, polling carries on: %s", err)
                delay = min(delay * 2, RETRY_LONGEST)
            self.connected = False
            if self.following:
                await asyncio.sleep(delay)

    async def _read_stream(self) -> None:
        timeout = aiohttp.ClientTimeout(
            total=None, sock_connect=15, sock_read=SILENCE_LIMIT
        )
        async with self._session.get(
            LIVE_STREAM_URL,
            headers={"User-Agent": USER_AGENT, "Accept": "text/event-stream"},
            timeout=timeout,
        ) as resp:
            resp.raise_for_status()
            self.connected = True
            _LOGGER.debug("Live stream connected")
            lines: list[str] = []
            async for raw in resp.content:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line:
                    field_name, _, value = line.partition(":")
                    if field_name == "data":
                        lines.append(value.removeprefix(" "))
                    continue
                if not lines:
                    continue
                text = "\n".join(lines)
                lines = []
                for kind, body in split_messages(text):
                    # Every game of the day comes through; keep ours only.
                    if str(body.get("gameUuid") or "") in self.following:
                        self.recent.append(text[:2000])
                        _LOGGER.debug("Live message: %s", text[:1000])
                        self._on_message(kind, body)


def _phase(value: Any) -> str | None:
    if not value:
        return None
    raw = str(value).replace("_", "").replace(" ", "").lower()
    return PHASES.get(raw, raw)


def _team_code(side: dict[str, Any]) -> str | None:
    return side.get("teamCode") or side.get("teamId") or None


def _number(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _player(name: Any, number: Any) -> str | None:
    if not name:
        return None
    return f"#{number} {name}" if number not in (None, "") else str(name)


def _assist_name(item: Any) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    if isinstance(item, dict):
        name = item.get("name") or " ".join(
            str(p) for p in (item.get("firstName"), item.get("lastName")) if p
        )
        return _player(name, item.get("playerNumber") or item.get("jersey"))
    return None
