"""End-to-end demo for the VLR Daily Digest Bot.

Because some networks block vlr.gg, this script builds a realistic vlr.gg-style
page dated *today*, then runs the full pipeline (parse -> Gemini ranking ->
format -> send to Telegram). It exercises everything except the live scrape,
which is covered by the unit tests in ``tests/test_vlr.py``.

Usage:
    python scripts/demo.py            # parse + rank + print the message
    python scripts/demo.py --send     # also send the message to Telegram

Requires TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (and optionally GEMINI_API_KEY)
in the environment or a local ``.env`` file.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone

# Make the package importable when running this script directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv  # noqa: E402

# A representative spread covering every priority tier.
# (team1, team2, event, series, time)
SAMPLE_MATCHES = [
    ("Paper Rex", "DRX", "VCT 2026: Pacific Stage 2", "Week 5", "10:00 AM"),
    ("Team Heretics", "FNATIC", "VCT 2026: EMEA Stage 2", "Playoffs–Upper Final", "7:00 PM"),
    ("EDward Gaming", "Bilibili Gaming", "VCT 2026: China Stage 2", "Week 5", "12:00 PM"),
    ("Sentinels", "G2 Esports", "VCT 2026: Americas Stage 2", "Week 5", "11:00 PM"),
    ("Team Liquid", "Karmine Corp", "Esports World Cup 2026", "Group Stage", "6:00 PM"),
    ("Spain", "France", "Esports Nation Cup 2026", "Semifinal", "8:00 PM"),
    (
        "UCAM Esports",
        "Barça eSports",
        "Challengers 2026: Spain Rising Stage 3",
        "Semifinal",
        "5:00 PM",
    ),
    ("BBL Esports", "CGN Esports", "Challengers 2026: EMEA Stage 3", "Group Stage", "4:30 PM"),
    (
        "Gentle Mates",
        "Mandatory",
        "Challengers 2026: France Revolution Split 2",
        "Week 3",
        "9:00 PM",
    ),
    ("REJECT", "IGZIST", "Challengers 2026: Japan Split 2", "Main Stage–Week 4", "9:00 AM"),
    (
        "Shopify Rebellion GC",
        "Version1 GC",
        "Game Changers 2026: NA Stage 2",
        "Playoffs",
        "10:00 PM",
    ),
    ("Maryville University", "Northwood", "Collegiate Valorant 2026", "Quarterfinal", "1:00 AM"),
]


def _build_html() -> str:
    today = datetime.now(timezone.utc).date()
    label = today.strftime("%a, %B %d, %Y")
    cards = []
    for i, (t1, t2, event, series, time) in enumerate(SAMPLE_MATCHES):
        cards.append(
            f"""
        <a class="wf-module-item match-item" href="/{1000 + i}/demo-match-{i}">
          <div class="match-item-time">{time}</div>
          <div class="match-item-vs">
            <div class="match-item-vs-team"><div class="match-item-vs-team-name"><span class="text-of">{t1}</span></div></div>
            <div class="match-item-vs-team"><div class="match-item-vs-team-name"><span class="text-of">{t2}</span></div></div>
          </div>
          <div class="match-item-event text-of">
            <div class="match-item-event-series text-of">{series}</div>
            {event}
          </div>
        </a>"""
        )
    return (
        f'<html><body><div class="wf-label mod-large">{label}</div>{"".join(cards)}</body></html>'
    )


def main() -> None:
    load_dotenv()
    send = "--send" in sys.argv[1:]

    from vlr_digest import llm, telegram, vlr

    html = _build_html()
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as fh:
        fh.write(html)
        os.environ["VLR_HTML_FILE"] = fh.name

    matches = vlr.fetch_upcoming_matches(days_ahead=2, max_matches=40)
    print(f"Parsed {len(matches)} demo matches.\n")

    rankings = llm.rank_matches(matches)
    message = llm.format_digest(matches, rankings)
    print(message)

    if send:
        print("\n=== sending to Telegram ===")
        res = telegram.send_message("🧪 <b>DEMO</b>\n\n" + message)
        print("ok:", res.get("ok"), "message_id:", res.get("result", {}).get("message_id"))
    else:
        print("\n(use --send to deliver this to Telegram)")


if __name__ == "__main__":
    main()
