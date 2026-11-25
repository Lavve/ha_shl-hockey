# Contributing

Thanks for wanting to help! Please read [AGENTS.md](AGENTS.md) first. It describes the principles, the structure and the conventions of this project.

## Add or improve a translation

1. Copy `custom_components/shl/translations/en.json` to a new file named after the [language code](https://developers.home-assistant.io/docs/internationalization/core/), e.g. `de.json`.
2. Translate the **values** only. Never change the keys.
3. Keep the same structure as `en.json`. Every key in `en.json` must exist in your file.
4. Open a pull request.

Team names come from SHL and are not translated.

## Report a bug

Open an [issue](https://github.com/Lavve/ha_shl-hockey/issues) and include:

- Home Assistant version and integration version.
- What you expected and what happened.
- Debug logs, enabled with:

  ```yaml
  logger:
    logs:
      custom_components.shl: debug
  ```

## Code changes

- Keep it simple. Open an issue to discuss larger changes first.
- Do not make the integration poll shl.se more often.
- No pre-formatted dates or numbers in states or attributes.
- Code, comments and commit messages in English.
- Commit messages: `<type>: <change>`, e.g. `fix: handle postponed games`. Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `ci`.

Test without Home Assistant:

```
pip install aiohttp
python scripts/test_api.py        # live request to shl.se
python scripts/test_schedule.py   # polling rules, no network
```

Pull requests must pass the **Validate** workflow (HACS action and hassfest).
