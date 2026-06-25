"""Centralised configuration read from environment variables.

Keeping all environment access in one module makes the rest of the codebase
easy to test and reason about.
"""

from __future__ import annotations

import os

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_DAYS_AHEAD = 2
DEFAULT_MAX_MATCHES = 40

# Variables the bot cannot run without.
REQUIRED_ENV: tuple[str, ...] = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


def gemini_api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY")


def gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)


def telegram_bot_token() -> str:
    return os.environ["TELEGRAM_BOT_TOKEN"]


def telegram_chat_id() -> str:
    return os.environ["TELEGRAM_CHAT_ID"]


def days_ahead() -> int:
    return int(os.getenv("DIGEST_DAYS_AHEAD", str(DEFAULT_DAYS_AHEAD)))


def max_matches() -> int:
    return int(os.getenv("DIGEST_MAX_MATCHES", str(DEFAULT_MAX_MATCHES)))


def vlr_html_file() -> str | None:
    """Optional path to a local HTML file to parse instead of fetching vlr.gg.

    Useful for offline testing/debugging (e.g. when the network blocks vlr.gg).
    """
    return os.getenv("VLR_HTML_FILE")


def missing_required_env() -> list[str]:
    """Return the names of required environment variables that are not set."""
    return [name for name in REQUIRED_ENV if not os.getenv(name)]
