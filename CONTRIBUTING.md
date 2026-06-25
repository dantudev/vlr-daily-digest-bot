# Contributing

Thanks for your interest in improving the **VLR Daily Digest Bot**! This guide
covers the local setup, coding standards, and workflow.

## Project layout

```
src/vlr_digest/
  __init__.py
  __main__.py        # enables `python -m vlr_digest`
  config.py          # environment / configuration access
  vlr.py             # scrape + parse upcoming matches from vlr.gg
  llm.py             # Gemini ranking + Telegram message formatting
  telegram.py        # Telegram Bot API client
  main.py            # orchestrator
tests/               # offline unit tests (pytest)
.github/workflows/   # daily.yml (cron) + ci.yml (lint/test)
```

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # runtime + dev tooling
pre-commit install           # enable git hooks
cp .env.example .env         # then fill in your secrets
```

## Running

```bash
python -m vlr_digest          # run the full digest pipeline
python -m vlr_digest.vlr      # debug: print parsed matches as JSON
```

## Code style & quality

- **Formatter & linter:** [Ruff](https://docs.astral.sh/ruff/) handles both
  formatting (`ruff format`, Black-compatible) and linting (`ruff check`),
  line length 100.
- **Tests:** [pytest](https://docs.pytest.org/) — keep unit tests offline (no network).

Run everything locally before pushing:

```bash
ruff check .
ruff format --check .
pytest
```

Or simply rely on `pre-commit` (runs on every commit) and CI (runs on every PR).

## Commit & PR guidelines

- Use clear, imperative commit messages (e.g. `Add region hint for China`).
- Keep PRs focused and small where possible.
- Ensure CI is green and add/adjust tests for behavioural changes.
- Never commit secrets. `.env` is git-ignored; use `.env.example` as the template.

## Secrets

The bot needs these environment variables (configured as GitHub Actions secrets
for deployment):

| Variable             | Required | Description                                   |
| -------------------- | -------- | --------------------------------------------- |
| `TELEGRAM_BOT_TOKEN` | yes      | Bot token from @BotFather                     |
| `TELEGRAM_CHAT_ID`   | yes      | Target chat / user ID                         |
| `GEMINI_API_KEY`     | no       | Gemini key (falls back to heuristic ranking)  |
| `GEMINI_MODEL`       | no       | Defaults to `gemini-2.5-flash`                |
| `DIGEST_DAYS_AHEAD`  | no       | Days of schedule to include (default `2`)     |
| `DIGEST_MAX_MATCHES` | no       | Max matches per digest (default `40`)         |
