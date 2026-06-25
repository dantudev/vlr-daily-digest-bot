"""Orchestrator for the VLR daily digest bot.

Flow:
    1. Fetch upcoming matches from vlr.gg.
    2. Ask Gemini to rank them (with a heuristic fallback).
    3. Format a compact Telegram digest.
    4. Send it to the configured chat.

Run locally with a populated ``.env`` file, or in GitHub Actions with the
secrets configured as environment variables.
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

from . import config, llm, telegram, vlr


def _check_env() -> None:
    missing = config.missing_required_env()
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)
    if not config.gemini_api_key():
        print("[warn] GEMINI_API_KEY not set — using heuristic ranking fallback.")


def build_digest_message() -> str:
    """Fetch upcoming matches, rank them, and return the formatted digest."""
    print("Fetching upcoming matches from vlr.gg…")
    matches = vlr.fetch_upcoming_matches()
    print(f"Found {len(matches)} matches.")

    print("Ranking matches with Gemini…")
    rankings = llm.rank_matches(matches)
    return llm.format_digest(matches, rankings)


def main() -> None:
    load_dotenv()
    _check_env()

    message = build_digest_message()
    print("Sending digest to Telegram…")
    telegram.send_message(message)
    print("Done.")


if __name__ == "__main__":
    main()
