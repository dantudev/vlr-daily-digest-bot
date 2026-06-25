"""Fetch and parse upcoming Valorant matches from vlr.gg.

The module scrapes https://www.vlr.gg/matches (the upcoming schedule page) and
returns a list of structured match dictionaries. No third-party API key is
required.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from . import config

VLR_MATCHES_URL = "https://www.vlr.gg/matches"

# vlr.gg renders match times in US Eastern time for anonymous requests; we
# convert everything to the player's local timezone (Spain / CEST).
SOURCE_TZ = ZoneInfo("America/New_York")
LOCAL_TZ = ZoneInfo("Europe/Madrid")

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
_TIME_FORMATS = ("%I:%M %p", "%H:%M")


def _to_local_datetime(match_date, time_text: str) -> datetime | None:
    """Combine a vlr.gg date + time into a timezone-aware local datetime.

    The vlr.gg time is interpreted as US Eastern (its default for anonymous
    requests) and converted to ``LOCAL_TZ`` (Europe/Madrid / CEST). Returns
    ``None`` if the time cannot be parsed (e.g. "TBD").
    """
    if not match_date or not time_text:
        return None
    cleaned = time_text.strip().upper().replace(".", "")
    for fmt in _TIME_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt).time()
        except ValueError:
            continue
        source = datetime.combine(match_date, parsed, tzinfo=SOURCE_TZ)
        return source.astimezone(LOCAL_TZ)
    return None


def _parse_label_date(label_text: str) -> date | None:
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


def _parse_match(item, match_date) -> tuple[dict, datetime | None]:
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

    # Convert the kickoff time to local (CEST) time. The local date can differ
    # from the vlr.gg (US) date for late-night matches.
    start_dt = _to_local_datetime(match_date, match_time)
    display_time = start_dt.strftime("%H:%M") if start_dt else match_time
    if start_dt is not None:
        date_iso = start_dt.date().isoformat()
    else:
        date_iso = match_date.isoformat() if match_date else None

    match = {
        "team1": team1,
        "team2": team2,
        "time": display_time,
        "date": date_iso,
        "event": event or "Unknown event",
        "series": series,
        "region": _region_hint(event),
        "eta": eta,
        "url": url,
    }
    return match, start_dt


def parse_matches(html: str, max_matches: int, day_start_hour: int) -> list[dict]:
    """Parse the vlr.gg matches HTML into structured matches for one digest day.

    A digest "day" runs from ``day_start_hour`` (local/CEST) today until the
    same hour tomorrow, so the message only covers matches the player can watch
    within that window.
    """
    soup = BeautifulSoup(html, "html.parser")

    now_local = datetime.now(LOCAL_TZ)
    day_start = now_local.replace(hour=day_start_hour, minute=0, second=0, microsecond=0)
    if now_local < day_start:
        # Before the daily cut-off we are still inside yesterday's digest day.
        day_start -= timedelta(days=1)
    window_end = day_start + timedelta(days=1)

    # Coarse label-date bounds expressed in the source (vlr.gg / US) timezone,
    # used only to stop scanning early.
    src_start_date = day_start.astimezone(SOURCE_TZ).date()
    src_end_date = window_end.astimezone(SOURCE_TZ).date()

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
            if current_date < src_start_date:
                continue
            if current_date > src_end_date:
                break  # Schedule is chronological; nothing later is in range.

        match, start_dt = _parse_match(node, current_date)
        # Skip fully undecided placeholder matches.
        if match["team1"] == "TBD" and match["team2"] == "TBD":
            continue

        # Keep only matches whose kickoff falls inside the digest-day window.
        if start_dt is not None:
            if not (day_start <= start_dt < window_end):
                continue
        elif current_date is None or not (src_start_date <= current_date <= src_end_date):
            continue

        matches.append(match)
        if len(matches) >= max_matches:
            break

    return matches


def fetch_upcoming_matches(max_matches: int | None = None) -> list[dict]:
    """Return matches for the current digest day (local/CEST window).

    Args:
        max_matches: Hard safety cap on the number of matches returned.
            Defaults to the ``DIGEST_MAX_MATCHES`` environment variable.
    """
    max_matches = config.max_matches() if max_matches is None else max_matches
    day_start_hour = config.day_start_hour()

    html_file = config.vlr_html_file()
    if html_file:
        # Offline mode: parse a local HTML snapshot instead of hitting the network.
        with open(html_file, encoding="utf-8") as fh:
            html = fh.read()
        return parse_matches(html, max_matches=max_matches, day_start_hour=day_start_hour)

    response = requests.get(VLR_MATCHES_URL, headers=_HEADERS, timeout=30)
    response.raise_for_status()

    return parse_matches(response.text, max_matches=max_matches, day_start_hour=day_start_hour)


if __name__ == "__main__":
    import json

    data = fetch_upcoming_matches()
    print(f"Fetched {len(data)} matches")
    print(json.dumps(data, indent=2, ensure_ascii=False))
