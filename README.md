# VLR Daily Digest Bot

Automated system that delivers a personalized Valorant match digest every day via Telegram.

## Features

- Fetches upcoming Valorant matches
- Filters and ranks matches based on competitive relevance
- Uses LLM (Gemini) to generate structured summaries
- Sends daily digest to Telegram
- Runs automatically via GitHub Actions (no server required)

## Stack

- Python
- GitHub Actions (cron automation)
- Gemini API
- Telegram Bot API
- VLR match data source

## Output example

- High priority matches (VCT / top teams)
- Medium priority (regional Tier 2)
- Low priority filler matches

## Project structure

```
src/vlr_digest/
  __init__.py
  __main__.py        # enables `python -m vlr_digest`
  config.py          # environment / configuration access
  vlr.py             # scrape + parse upcoming matches from vlr.gg
  llm.py             # Gemini ranking (high/medium/low) + message formatting
  telegram.py        # Telegram Bot API client
  main.py            # orchestrator
tests/               # offline unit tests (pytest)
.github/workflows/   # daily.yml (cron 10:00 UTC) + ci.yml (lint/test)
pyproject.toml       # packaging + Ruff/Black/pytest config
requirements.txt     # runtime deps (used by the workflow)
requirements-dev.txt # dev/tooling deps
```

## How it works

1. `vlr.py` scrapes [vlr.gg/matches](https://www.vlr.gg/matches) and parses each
   match into structured data (teams, event, stage, time, region hint, URL).
2. `llm.py` sends the matches to **Gemini**, which classifies each one as
   **high / medium / low** priority for an EMEA-focused (Spain) competitive
   player. If Gemini is unavailable, a keyword heuristic is used as a fallback so
   a digest is always delivered.
3. `telegram.py` posts the formatted, emoji-rich digest to your Telegram chat.

## Configuration

The bot reads the following environment variables (locally via a `.env` file,
or in GitHub Actions via repository **Secrets**):

| Variable             | Required | Description                          |
| -------------------- | -------- | ------------------------------------ |
| `TELEGRAM_BOT_TOKEN` | yes      | Bot token from @BotFather            |
| `TELEGRAM_CHAT_ID`   | yes      | Target chat / user ID                |
| `GEMINI_API_KEY`     | no\*     | Gemini API key (\*falls back to heuristic ranking if missing) |
| `GEMINI_MODEL`       | no       | Defaults to `gemini-2.5-flash`       |
| `DIGEST_DAY_START_HOUR` | no    | Hour (CEST) the digest day starts/ends (default `9`) |
| `DIGEST_MAX_MATCHES` | no       | Safety cap on matches per digest (default `60`) |

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # runtime + dev tooling
cp .env.example .env           # then fill in your secrets
python -m vlr_digest
```

Quality checks (also enforced in CI and via pre-commit):

```bash
ruff check .          # lint
ruff format --check . # formatting
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full developer guide.

## Deploy on GitHub Actions

1. In your repository: **Settings → Secrets and variables → Actions → New repository secret**
   and add `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID`.
2. The workflow [`.github/workflows/daily.yml`](.github/workflows/daily.yml) runs
   automatically every day at **10:00 UTC** and can also be triggered manually
   from the **Actions** tab (workflow_dispatch).

> The `.env` file is git-ignored — never commit your real keys. If keys were ever
> committed, rotate them.

