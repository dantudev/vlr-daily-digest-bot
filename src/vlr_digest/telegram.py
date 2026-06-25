"""Send messages to Telegram via the Bot API."""

from __future__ import annotations

import requests

from . import config

_API_BASE = "https://api.telegram.org"
_MAX_LENGTH = 4096


def send_message(text: str) -> dict:
    """Send ``text`` to the configured Telegram chat.

    Long messages are split into multiple Telegram messages. Returns the API
    response of the last message sent.
    """
    token = config.telegram_bot_token()
    chat_id = config.telegram_chat_id()
    url = f"{_API_BASE}/bot{token}/sendMessage"

    result: dict = {}
    for chunk in _split(text):
        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
    return result


def _split(text: str) -> list[str]:
    if len(text) <= _MAX_LENGTH:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > _MAX_LENGTH:
            chunks.append(current.rstrip())
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current.rstrip())
    return chunks
