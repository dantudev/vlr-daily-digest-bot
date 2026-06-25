"""Fetch and parse upcoming Valorant matches from vlr.gg.

The module scrapes https://www.vlr.gg/matches (the upcoming schedule page) and
returns a list of structured match dictionaries. No third-party API key is
required.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from . import config

VLR_MATCHES_URL = "https://www.vlr.gg/matches"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Keyword buckets used only for a coarse region hint (the LLM does the real
# prioritisation). Order matters: the first match wins.
_REGION_HINTS = [
    ("Spain", ["spain", "españa", "espana"]),
    ("EMEA", ["emea", "europe", "iberian", "iberia"]),
    ("International", ["masters", "champions", "vct ", "valorant champions tour"]),
    ("Americas", ["americas", "latam", "north america", "brazil", "na "]),
    ("Pacific", ["pacific", "korea", "japan", "south asia", "southeast asia", "oceania"]),
    ("China", ["china", "fgc"]),
]

_DATE_RE = re.compile(r"([A-Za-z]+\s+\d{1,2},\s+\d{4})")


def _parse_label_date(label_text: str) -> datetime.date | None:
    """Extract a ``date`` object from a vlr.gg date header, or ``None``."""
    match = _DATE_RE.search(label_text or "")
    if not match:
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(match.group(1), fmt).date()
        except ValueError:
            continue
    return None


def _region_hint(event: str) -> str:
    text = (event or "").lower()
    for region, keywords in _REGION_HINTS:
        if any(keyword in text for keyword in keywords):
            return region
    return "Unknown"


def _team_name(team_el) -> str:
    if team_el is None:
        return "TBD"
    name_el = team_el.select_one(".text-of") or team_el
    name = name_el.get_text(strip=True)
    return name or "TBD"


def _parse_match(item, match_date) -> dict:
    time_el = item.select_one(".match-item-time")
    match_time = time_el.get_text(strip=True) if time_el else "TBD"

    team_els = item.select(".match-item-vs-team-name")
    team1 = _team_name(team_els[0]) if len(team_els) > 0 else "TBD"
    team2 = _team_name(team_els[1]) if len(team_els) > 1 else "TBD"

    series_el = item.select_one(".match-item-event-series")
    series = series_el.get_text(" ", strip=True) if series_el else ""

    event_el = item.select_one(".match-item-event")
    event = ""
    if event_el:
        event = event_el.get_text(" ", strip=True)
        if series:
            event = event.replace(series, "").strip()
    event = re.sub(r"\s+", " ", event).strip()

    eta_el = item.select_one(".match-item-eta")
    eta = eta_el.get_text(" ", strip=True) if eta_el else ""

    href = item.get("href") or ""
    url = f"https://www.vlr.gg{href}" if href.startswith("/") else href

    return {
        "team1": team1,
        "team2": team2,
        "time": match_time,
        "date": match_date.isoformat() if match_date else None,
        "event": event or "Unknown event",
        "series": series,
        "region": _region_hint(event),
        "eta": eta,
        "url": url,
    }


def parse_matches(html: str, days_ahead: int, max_matches: int) -> list[dict]:
    """Parse the vlr.gg matches HTML into structured, date-filtered matches."""
    soup = BeautifulSoup(html, "html.parser")

    today = datetime.now(timezone.utc).date()
    cutoff = today + timedelta(days=days_ahead)

    # Date labels and match cards appear as siblings in document order.
    nodes = soup.select("div.wf-label.mod-large, a.wf-module-item.match-item")

    matches: list[dict] = []
    current_date = None

    for node in nodes:
        classes = node.get("class") or []
        if "wf-label" in classes:
            current_date = _parse_label_date(node.get_text(" ", strip=True))
            continue

        # It's a match item.
        if current_date is not None:
            if current_date < today:
                continue
            if current_date > cutoff:
                break  # Schedule is chronological; nothing later is in range.

        match = _parse_match(node, current_date)
        # Skip fully undecided placeholder matches.
        if match["team1"] == "TBD" and match["team2"] == "TBD":
            continue

        matches.append(match)
        if len(matches) >= max_matches:
            break

    return matches


def fetch_upcoming_matches(
    days_ahead: int | None = None, max_matches: int | None = None
) -> list[dict]:
    """Return upcoming matches for the next ``days_ahead`` days.

    Args:
        days_ahead: How many days past today (UTC) to include. Defaults to the
            ``DIGEST_DAYS_AHEAD`` environment variable.
        max_matches: Hard cap on the number of matches returned. Defaults to the
            ``DIGEST_MAX_MATCHES`` environment variable.
    """
    days_ahead = config.days_ahead() if days_ahead is None else days_ahead
    max_matches = config.max_matches() if max_matches is None else max_matches

    html_file = config.vlr_html_file()
    if html_file:
        # Offline mode: parse a local HTML snapshot instead of hitting the network.
        with open(html_file, encoding="utf-8") as fh:
            html = fh.read()
        return parse_matches(html, days_ahead=days_ahead, max_matches=max_matches)

    response = requests.get(VLR_MATCHES_URL, headers=_HEADERS, timeout=30)
    response.raise_for_status()

    return parse_matches(response.text, days_ahead=days_ahead, max_matches=max_matches)


if __name__ == "__main__":
    import json

    data = fetch_upcoming_matches()
    print(f"Fetched {len(data)} matches")
    print(json.dumps(data, indent=2, ensure_ascii=False))
