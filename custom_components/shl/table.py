"""Work out the standings from the results.

SHL enters a result at the final whistle but publishes the updated table a
while later. Until it has caught up, the table is calculated from the
schedule's results, so it is right as soon as the game is over. The official
table always takes over again once it counts every game.

No Home Assistant imports, so it can be tested with scripts/test_api.py
against SHL's own table.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .models import Game, Standing

# Points for each kind of result.
POINTS_WIN = 3
POINTS_EXTRA_WIN = 2  # overtime or shootout
POINTS_EXTRA_LOSS = 1


@dataclass(slots=True)
class _Row:
    code: str
    name: str
    logo: str | None
    games_played: int = 0
    wins: int = 0
    overtime_wins: int = 0
    losses: int = 0
    overtime_losses: int = 0
    goals_for: int = 0
    goals_against: int = 0

    @property
    def points(self) -> int:
        return (
            self.wins * POINTS_WIN
            + self.overtime_wins * POINTS_EXTRA_WIN
            + self.overtime_losses * POINTS_EXTRA_LOSS
        )


def standings_from_games(
    games: Sequence[Game], official: Sequence[Standing] = ()
) -> list[Standing]:
    """Return the table calculated from the played games.

    Names and logos come from the official table when there is one. Teams
    level on points, goal difference and goals scored keep their order from
    the official table, which stands in for the head-to-head rules we do not
    know.
    """
    previous = {row.team_code: row for row in official}
    rows: dict[str, _Row] = {
        code: _Row(code, row.name, row.logo) for code, row in previous.items()
    }

    for game in games:
        home, away = game.home, game.away
        if (
            not game.is_played
            or home.code is None
            or away.code is None
            or home.score is None
            or away.score is None
            or home.score == away.score
        ):
            continue
        extra = game.overtime or game.shootout
        for team, own, other in (
            (home, home.score, away.score),
            (away, away.score, home.score),
        ):
            row = rows.setdefault(
                team.code, _Row(team.code, team.name or team.code, team.logo)
            )
            row.games_played += 1
            row.goals_for += own
            row.goals_against += other
            if own > other:
                if extra:
                    row.overtime_wins += 1
                else:
                    row.wins += 1
            elif extra:
                row.overtime_losses += 1
            else:
                row.losses += 1

    def order(row: _Row) -> tuple[int, int, int, int]:
        official_rank = previous[row.code].rank if row.code in previous else 999
        return (
            -row.points,
            -(row.goals_for - row.goals_against),
            -row.goals_for,
            official_rank,
        )

    return [
        Standing(
            rank=rank,
            team_code=row.code,
            name=row.name,
            logo=row.logo,
            games_played=row.games_played,
            wins=row.wins,
            overtime_wins=row.overtime_wins,
            losses=row.losses,
            overtime_losses=row.overtime_losses,
            goals_for=row.goals_for,
            goals_against=row.goals_against,
            points=row.points,
        )
        for rank, row in enumerate(sorted(rows.values(), key=order), start=1)
    ]
