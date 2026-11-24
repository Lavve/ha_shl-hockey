# SHL Hockey (unofficial)

A Home Assistant integration that shows games, results and standings from the
Swedish Hockey League (SHL) for your favorite teams.

> [!IMPORTANT]
> This integration is **not affiliated with or endorsed by SHL**. It uses
> shl.se's public but **unofficial** API, which may change or stop working at
> any time. All data belongs to SHL.

<p align="center">
  <img src="images/unplayed.png" alt="Next game and upcoming games" width="32%" align="top">
  <img src="images/played.png" alt="Latest results" width="32%" align="top">
  <img src="images/table.png" alt="Standings" width="32%" align="top">
</p>

<sub>Example dashboard built with Markdown and flex-table cards using this integration's sensors. The cards themselves are not part of the integration – see [Dashboard examples](#dashboard-examples).</sub>

## Features

- Pick one or more favorite teams.
- Next game, last result and table position per team.
- The full standings table.
- Adaptive polling: data is fetched often only when your teams play.
- Follows your Home Assistant language and date/number format.
- Handles season changes and playoffs automatically.

There are no live updates (goals, periods) – see [How data is fetched](#how-data-is-fetched).

## Installation

### Marketplace (recommended)

1. Go to **Settings → Marketplace → Custom repositories**.
2. Add `https://github.com/Lavve/ha_shl-hockey` with the type **Integration**.
3. Find **SHL Hockey (unofficial)** and install it.

### Manual

Copy `custom_components/shl` to `config/custom_components/shl` in your
Home Assistant configuration folder and restart Home Assistant.

## Setup

[![Open your Home Assistant instance and start setting up the integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=shl)

Or go to **Settings → Devices & services → Add integration** and search for
**SHL Hockey**. Select your favorite teams. You can change them later with
**Configure**.

## Entities

Each favorite team gets its own device with four sensors. Entity IDs below use
Frölunda HC as an example.

| Entity | State | Description |
|---|---|---|
| `sensor.frolunda_hc_next_game` | Start time | The next or ongoing game. |
| `sensor.frolunda_hc_last_game` | Result | `win`, `loss`, `overtime_win`, `overtime_loss`, `shootout_win` or `shootout_loss`. |
| `sensor.frolunda_hc_position` | Number | Position in the standings. |
| `sensor.frolunda_hc_games_played` | Number | Games played this season. All of the season's games in the `games` attribute. Disabled by default – enable it on the team's device page. |

The **SHL** device has one sensor:

| Entity | State | Description |
|---|---|---|
| `sensor.shl_standings` | Season, e.g. `2026/2027` | The full table in the `table` attribute. |

### Attributes

**Next game:** `status` (`upcoming`, `in_progress`), `opponent`,
`opponent_logo`, `home_game`, `venue`, `home_team`, `away_team`, `home_logo`,
`away_logo`

**Last game:** `start`, the same game attributes as above, `home_score`,
`away_score`

**Position:** `points`, `games_played`, `wins`, `overtime_wins`,
`overtime_losses`, `losses`, `goals_for`, `goals_against`, `goal_difference`

**Games played:** `games` – all of the team's games this season, played and
upcoming, oldest first. Each game has `start`, `game_type` (`regular`,
`playoff`, `qualdown`), `played`, `result` (as for the last game, `null` if not
played), `home_game`, `home_code`, `away_code`, `home_team`, `away_team`,
`home_logo`, `away_logo`, `home_score`, `away_score` and `venue`. The list is
not saved in the recorder database.

**Standings:** `table` – a list with one item per team containing `rank`,
`team_code`, `name`, `logo` and the same numbers as the position sensor. The
table is not saved in the recorder database.

Wins and losses (`wins`, `losses`) are in regulation time. Overtime and shootout
results are counted in `overtime_wins` and `overtime_losses`.

Team logos are linked from shl.se, not included in this repository.

## Dashboard examples

Next game, formatted by Home Assistant in your language:

```yaml
type: tile
entity: sensor.frolunda_hc_next_game
```

Standings in a Markdown card:

```yaml
type: markdown
content: |
  | # | Team | GP | +/- | P |
  |--:|:--|--:|--:|--:|
  {% for r in state_attr('sensor.shl_standings', 'table') or [] -%}
  | {{ r.rank }} | {{ r.name }} | {{ r.games_played }} | {{ r.goal_difference }} | {{ r.points }} |
  {% endfor %}
```

The last five results, newest first:

```yaml
type: markdown
content: |
  {% set games = state_attr('sensor.frolunda_hc_games_played', 'games') or [] %}
  {% for g in (games | selectattr('played') | list | reverse | list)[:5] -%}
  {{ g.home_team }} {{ g.home_score }}–{{ g.away_score }} {{ g.away_team }}
  {% endfor %}
```

## Automation example

A notification five minutes before puck drop. The time trigger follows the next game sensor, so it moves to the next game by itself.

```yaml
alias: Frölunda plays in five minutes
triggers:
  - trigger: time
    at:
      entity_id: sensor.frolunda_hc_next_game
      offset: "-00:05:00"
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: 🏒 Frölunda plays in five minutes!
      message: >-
        {{ state_attr('sensor.frolunda_hc_next_game', 'home_team') }} –
        {{ state_attr('sensor.frolunda_hc_next_game', 'away_team') }}
        · {{ state_attr('sensor.frolunda_hc_next_game', 'venue') }}
mode: single
```

Replace `notify.mobile_app_your_phone` with your own notify action.

## How data is fetched

The integration only talks to shl.se and tries to be gentle with it. How often
it fetches depends on your favorite teams:

| Situation | Interval |
|---|---|
| One of your teams is playing | every 5 minutes |
| One of your teams plays within 6 hours | every 30 minutes (and at puck drop) |
| Otherwise | every 8 hours |

The standings are only fetched when a game has finished. The current season is
checked weekly, and daily once the regular season is over, so playoffs and new
seasons are picked up automatically.

The intervals cannot be changed. If you want full control, turn off polling in
the integration's **System options** and call `homeassistant.update_entity`
from an automation.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). New translations are very welcome.

## License

[MIT](LICENSE)
