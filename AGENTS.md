# AGENTS.md

Guidance for AI agents (and humans) working in this repository.

## Project

**SHL Hockey (unofficial)** – a Home Assistant custom integration (HACS) that
shows games, results and standings from the Swedish Hockey League (SHL).
Data comes from shl.se's **unofficial** API. There is no official API, so we
treat it with care.

- Domain: `shl` (cannot be changed after release)
- Target: the latest Home Assistant release, Python version as required by it
- No external Python dependencies – only what Home Assistant ships (`aiohttp`)

## Principles

1. **Keep it simple.** Do not add features, abstractions or files that are not
   needed now.
2. **Be gentle with shl.se.**
   - Never poll more often than every 5 minutes (`MIN_INTERVAL`).
   - No live updates. Adaptive polling only (see `schedule.py`).
   - Polling intervals are not user-configurable (Home Assistant guideline).
     Users who want manual control can disable polling and call
     `homeassistant.update_entity`.
   - One coordinator per installation (`single_config_entry`), one request per
     endpoint regardless of how many teams are selected.
   - Always send our own `User-Agent`.
   - The integration calls shl.se directly – no proxy or middleman.
3. **Respect the user's language and locale.**
   - Never put pre-formatted text (dates, times, numbers) in states or
     attributes. Use raw values.
   - Times are timezone-aware UTC `datetime`s, exposed as
     `SensorDeviceClass.TIMESTAMP`, so the frontend formats them.
   - Numbers are real `int`/`float`.
   - All entity names and enum states use `translation_key`.
   - Team names come from SHL and are not translated.
4. **Out of scope:** TV channels (separate integration), live play-by-play,
   team logos bundled in the repo.

## Structure

```
custom_components/shl/
  const.py        Constants. No Home Assistant imports.
  models.py       Dataclasses (raw values). No Home Assistant imports.
  api.py          shl.se client + parsing. No Home Assistant imports.
  schedule.py     Polling rules (pure functions). No Home Assistant imports.
  coordinator.py  DataUpdateCoordinator – uses api.py and schedule.py.
  __init__.py     Setup / unload of the config entry.
  config_flow.py  Config flow + options flow.
  sensor.py       Entities.
  manifest.json
  icons.json      Entity icons (by translation_key).
  brand/          icon.png, icon@2x.png (own artwork, no SHL logo).
  translations/   en.json (source), sv.json, ...
scripts/          Manual test scripts that run without Home Assistant.
.github/workflows/validate.yaml   HACS action + hassfest.
hacs.json         Marketplace metadata (must be in every release).
```

`const.py`, `models.py`, `api.py` and `schedule.py` must stay free of
Home Assistant imports so they can be tested with the scripts in `scripts/`.

## Code conventions

- Code, comments, docstrings, logs and commit messages in **English**.
- Follow current Home Assistant patterns: `ConfigEntry.runtime_data`,
  `DataUpdateCoordinator(config_entry=...)`, `_attr_has_entity_name = True`,
  `translation_key`, devices per team.
- Type hints everywhere, `from __future__ import annotations`.
- Parsing is defensive: one malformed game or row is skipped and logged at
  debug level, it must not break the whole update.
- When shl.se fails, keep the last known data where possible.

## shl.se API notes

| Endpoint | Params | Notes |
|---|---|---|
| `/api/sports-v2/season-series-game-types-filter` | none (params are ignored) | `defaultSsgtFilter` + `ssgtUuid` = current selection. Game types have stable `code`s: `regular`, `playoff`, `qualdown`. |
| `/api/sports-v2/game-schedule` | `seasonUuid`, `seriesUuid`, `gameTypeUuid`, `gamePlace=all`, `played=all` | Object with `gameInfo` list. Times in `rawStartDateTime` (UTC). Each game has its own `ssgtUuid`. |
| `/api/statistics-v2/stats-info/standings_standings` | `ssgtUuid`, `provider=statnet`, `count=25` | List with one object: `teams` (keyed by team code) and `stats`. `W`/`L` are regulation only; `Points` is total. |

- Observed game `state` values: `pre-game`, `post-game`. Anything else is
  treated as in progress. Score is `"N/A"` before a game.
- The default filter is believed to switch to playoffs in spring. We do not
  rely on it: game types are looked up by `code`, post-season games are
  fetched once the regular season is finished, and standings always use the
  regular season's `ssgtUuid`.

## Workflow

- Work in **small steps**. After each step, stop and wait for the
  maintainer's OK before continuing.
- **Do not commit or push.** The maintainer commits. After each step, propose
  one commit message in the format `<type>: <change>`, e.g.
  `feat: add adaptive polling schedule`.
  Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`.
- New user-facing strings go into `translations/en.json` first, then `sv.json`.
  Do not use `strings.json`.

## Releases

- Publish a **GitHub release** (a tag alone is not enough).
- The tag must equal `version` in `manifest.json` (and `VERSION` in
  `const.py`, used in the User-Agent).
- `hacs.json` must be in every release. Raise `homeassistant` in it when a
  release needs a newer Home Assistant.

## Testing

```
pip install aiohttp
python scripts/test_api.py          # live request to shl.se
python scripts/test_api.py FHC      # one team
```
