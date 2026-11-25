# Examples

Ready-to-copy dashboard cards and automations for the SHL integration. They are examples – adapt them to your own dashboard.

## How to use

- **Cards:** open your dashboard, **Edit dashboard → Add card → Manual**, and paste the contents of the file.
- **Automations:** **Settings → Automations & scenes → Create automation → ⋮ → Edit in YAML**, and paste the contents of the file.

All examples use Frölunda HC. Search and replace `frolunda_hc` with your team's entity prefix, e.g. `farjestad_bk` or `lulea_hockey`. You find it in the entity IDs on the team's device page.

## Cards

| File | Shows | Requires |
|---|---|---|
| [next_game.yaml](cards/next_game.yaml) | Countdown, live and final score | – (card-mod optional) |
| [upcoming_games.yaml](cards/upcoming_games.yaml) | The next five games | Games played sensor |
| [latest_results.yaml](cards/latest_results.yaml) | The five latest results | Games played sensor |
| [team_stats.yaml](cards/team_stats.yaml) | Position, points, record, home/away, form | Games played sensor, [button-card](https://github.com/custom-cards/button-card) |
| [standings.yaml](cards/standings.yaml) | The full standings table | [flex-table-card](https://github.com/custom-cards/flex-table-card) |

The **Games played** sensor is disabled by default. Enable it on the team's device page under **Settings → Devices & services → SHL**.

## Automations

| File | Does |
|---|---|
| [game_notification.yaml](automations/game_notification.yaml) | A notification five minutes before puck drop |
| [game_notification_calendar.yaml](automations/game_notification_calendar.yaml) | The same, with the calendar trigger – no templates needed |
| [goal_light.yaml](automations/goal_light.yaml) | Flashes a light when your team scores. Requires live updates. |

## Language and formats

The examples are in English. Dates and times in Markdown cards are formatted with `strftime`, which always uses English day names – change the text and formats to suit your language.
