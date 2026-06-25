"""LLM-powered ranking and Telegram message formatting.

`rank_matches` asks Gemini to classify each match as high / medium / low
priority for an EMEA-focused competitive player. `format_digest` turns the
ranked matches into a compact, emoji-rich Telegram message (HTML parse mode).

If the Gemini call fails for any reason, a deterministic keyword heuristic is
used as a fallback so the digest is always delivered.
"""

from __future__ import annotations

import html
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config

_MAX_RETRIES = 3
_RETRY_BACKOFF = 4  # seconds; multiplied by attempt number

_LOCAL_TZ = ZoneInfo("Europe/Madrid")

_VALID_PRIORITIES = ("high", "emea", "medium", "low")

# Keywords identifying "other" EMEA regional Challengers (below Spain Rising and
# the global EMEA Challengers, but still inside the EMEA-priority bucket).
_EMEA_REGIONAL_KEYWORDS = (
    "north",
    "east",
    "france",
    "revolution",
    "dach",
    "evolution",
    "ascension",
    "iberian",
    "italy",
    "portugal",
    "t\u00fcrkiye",
    "turkiye",
    "birlik",
)

# Keywords identifying Challengers regions OUTSIDE EMEA. These are checked
# before the (looser) EMEA regional keywords so that e.g. "North America" or
# "LATAM North" is never mistaken for an EMEA "North" league.
_NON_EMEA_CHALLENGERS_KEYWORDS = (
    "north america",
    "latam",
    "brazil",
    "japan",
    "korea",
    "pacific",
    "china",
    "oceania",
    "south asia",
    "southeast asia",
)

# Target number of matches in the digest. High Tier 1 and the top EMEA
# Challengers (Spain Rising + global EMEA) are ALWAYS shown in full, even if
# they exceed this; the remaining (lower-priority) sections only fill up to
# this total.
_MAX_TOTAL_MATCHES = 8

_SYSTEM_INSTRUCTION = """You are an expert Valorant esports analyst building a \
daily match digest for a competitive player based in Spain (EMEA region).

Classify every match into exactly one priority: "high", "emea", "medium" or
"low". Apply the rules in order; the first matching rule wins.

HIGH priority — Tier 1:
- VCT international LEAGUE matches. Order of interest: EMEA > Americas > Pacific
  > China.
- Global events featuring VCT (Tier 1) teams, e.g. VCT Masters, VCT Champions,
  Esports World Cup.
- National-team events, e.g. Esports Nation Cup.
  (Tier 1 events never contain the words "Challengers" or "Game Changers".)

EMEA priority — the top EMEA "Challengers" (above all other Challengers):
1. Challengers Spain Rising (event name usually contains "Spain Rising").
2. Global EMEA Challengers with the best teams, e.g. "Challengers ... EMEA
   Stage X".
3. Other EMEA regional Challengers, e.g. North/East, France Revolution,
   DACH Evolution, Ascension, Iberian, etc. (lowest within EMEA priority, but
   still prioritised above any non-EMEA Challengers). IMPORTANT: an event is
   only EMEA-regional when it clearly belongs to the EMEA circuit. Regions
   such as "North America", "LATAM North", "Pacific", etc. are NOT EMEA even
   though they contain words like "North" or "East".
Use priority "emea" for these three; every other Challengers event is
"medium".

MEDIUM priority — Challengers events outside EMEA, e.g. Challengers Japan,
North America, LATAM, Brazil, Korea, etc.

LOW priority — not relevant:
- Any Game Changers event (the entire circuit).
- College / Collegiate matches (US school teams).
- Anything that does not fit the categories above.

Within each priority, order matches following the interest order above.

Return ONLY valid JSON of the form:
{"rankings": [{"index": <int>, "priority": "high|emea|medium|low"}, ...]}
Include exactly one entry for every match index provided."""


def _build_user_prompt(matches: list[dict]) -> str:
    lines = ["Classify these matches:\n"]
    for i, m in enumerate(matches):
        lines.append(
            f"{i}. {m['team1']} vs {m['team2']} | event: {m['event']} | "
            f"stage: {m['series'] or 'n/a'} | region hint: {m['region']}"
        )
    return "\n".join(lines)


def _heuristic_priority(match: dict) -> str:
    """Deterministic fallback ranking that mirrors the Gemini rules."""
    event = (match.get("event") or "").lower()

    # LOW: irrelevant circuits (checked first — they may also contain region words).
    if "game changers" in event or "collegiate" in event or "college" in event:
        return "low"

    # HIGH (Tier 1): VCT leagues, global VCT events and national-team cups.
    tier1_keywords = (
        "masters",
        "champions",  # VCT Masters / Champions / "Champions Tour"
        "esports world cup",
        "world cup",
        "nation",  # Esports / Valorant Nation(s) Cup
    )
    if any(k in event for k in tier1_keywords):
        return "high"
    # VCT international leagues (EMEA/Americas/Pacific/China) — league play only,
    # never the "Challengers" tier.
    if ("vct" in event or "champions tour" in event) and "challengers" not in event:
        return "high"

    # EMEA priority: top EMEA Challengers (Spain Rising + global EMEA league)
    # plus other EMEA regional Challengers (lowest within the EMEA bucket).
    if "challengers" in event:
        if "spain rising" in event or "emea" in event:
            return "emea"
        # Challengers from other regions are "medium" — checked before the
        # looser EMEA-regional keywords ("north" would match "North America").
        if any(k in event for k in _NON_EMEA_CHALLENGERS_KEYWORDS):
            return "medium"
        if any(k in event for k in _EMEA_REGIONAL_KEYWORDS):
            return "emea"
        return "medium"

    return "low"


def _heuristic_rankings(matches: list[dict]) -> dict[int, str]:
    return {i: _heuristic_priority(m) for i, m in enumerate(matches)}


def _is_transient(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        code in text
        for code in (
            "503",
            "429",
            "unavailable",
            "overloaded",
            "high demand",
            "rate limit",
            "deadline",
        )
    )


def rank_matches(matches: list[dict]) -> dict[int, str]:
    """Return a mapping of match index -> priority ("high"/"medium"/"low")."""
    if not matches:
        return {}

    api_key = config.gemini_api_key()
    if not api_key:
        return _heuristic_rankings(matches)

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        gen_config = types.GenerateContentConfig(
            system_instruction=_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            temperature=0.2,
        )

        last_exc: Exception | None = None
        data = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = client.models.generate_content(
                    model=config.gemini_model(),
                    contents=_build_user_prompt(matches),
                    config=gen_config,
                )
                data = json.loads(response.text or "")
                break
            except Exception as exc:  # noqa: BLE001 - retry transient errors
                last_exc = exc
                if attempt < _MAX_RETRIES and _is_transient(exc):
                    wait = _RETRY_BACKOFF * attempt
                    print(
                        f"[llm] transient Gemini error (attempt {attempt}): {exc}; "
                        f"retrying in {wait}s"
                    )
                    time.sleep(wait)
                    continue
                raise
        if data is None:  # pragma: no cover - loop always breaks or raises
            raise last_exc  # type: ignore[misc]

        rankings = dict.fromkeys(range(len(matches)), "low")
        for entry in data.get("rankings", []):
            idx = entry.get("index")
            priority = str(entry.get("priority", "low")).lower()
            if isinstance(idx, int) and 0 <= idx < len(matches):
                rankings[idx] = priority if priority in _VALID_PRIORITIES else "low"
        return rankings
    except Exception as exc:  # noqa: BLE001 - always degrade gracefully
        print(f"[llm] Gemini ranking failed, using heuristic fallback: {exc}")
        return _heuristic_rankings(matches)


def _format_match_line(match: dict) -> str:
    team1 = html.escape(match["team1"])
    team2 = html.escape(match["team2"])
    event = html.escape(match["event"])
    series = html.escape(match["series"]) if match["series"] else ""
    match_time = html.escape(match["time"])
    url = match.get("url", "")

    header = f"<b>{team1}</b> vs <b>{team2}</b>"
    if url:
        header = f'<a href="{html.escape(url, quote=True)}">{header}</a>'

    event_line = f"🏆 {event}"
    if series:
        event_line += f" — {series}"

    return f"• {header}\n  {event_line}\n  🕒 {match_time}"


# Fixed display order for the VCT international leagues (HIGH priority).
_VCT_LEAGUE_REGIONS = ("EMEA", "Americas", "Pacific", "China")
_VCT_LEAGUE_ORDER = {region: i for i, region in enumerate(_VCT_LEAGUE_REGIONS)}


def _vct_league_region(event: str) -> str | None:
    """Return the VCT international league region for an event, or ``None``.

    Only matches genuine VCT *league* play (not Challengers / Game Changers).
    """
    e = (event or "").lower()
    if "challengers" in e or "game changers" in e:
        return None
    if "vct" not in e and "champions tour" not in e:
        return None
    for region in _VCT_LEAGUE_REGIONS:
        if region.lower() in e:
            return region
    return None


def _emea_order(event: str) -> int:
    """Interest order within the EMEA-priority bucket."""
    e = (event or "").lower()
    if "spain rising" in e:
        return 0  # Spain Rising first.
    # "north"/"east" must not pick up non-EMEA regions (e.g. North America).
    if any(k in e for k in _NON_EMEA_CHALLENGERS_KEYWORDS):
        return 1  # Treat as a global EMEA Challengers slot if it slipped in.
    if any(k in e for k in _EMEA_REGIONAL_KEYWORDS):
        return 2  # Other EMEA regional Challengers (lowest, space permitting).
    return 1  # Global EMEA Challengers.


def format_digest(matches: list[dict], rankings: dict[int, str]) -> str:
    """Build the Telegram message (HTML parse mode) from ranked matches."""
    today = datetime.now(_LOCAL_TZ).strftime("%d %b %Y")

    parts = [f"🎯 <b>Valorant Daily Digest</b> — {today}", "<i>Times in CEST (Europe/Madrid)</i>"]

    if not matches:
        parts.append("\nNo upcoming matches found for the next couple of days. 🌙")
        return "\n".join(parts)

    buckets: dict[str, list[dict]] = {"high": [], "emea": [], "medium": [], "low": []}
    for i, match in enumerate(matches):
        buckets[rankings.get(i, "low")].append(match)

    # --- HIGH: split VCT international leagues (fixed order) from other Tier 1 ---
    high = buckets["high"]
    if high:
        parts.append("\n🔥 <b>High Priority</b>")
        vct_league: list[tuple[str, dict]] = []
        other_tier1: list[dict] = []
        for match in high:
            region = _vct_league_region(match["event"])
            if region:
                vct_league.append((region, match))
            else:
                other_tier1.append(match)
        vct_league.sort(key=lambda pair: _VCT_LEAGUE_ORDER[pair[0]])

        if vct_league:
            parts.append("🌍 <b>VCT Leagues</b>")
            parts.extend(_format_match_line(match) for _, match in vct_league)
        if other_tier1:
            if vct_league:
                parts.append("")  # visual separator
            parts.append("🏅 <b>Other Tier 1</b>")
            parts.extend(_format_match_line(match) for match in other_tier1)

    # --- EMEA: top EMEA Challengers (Spain Rising + global EMEA league) ---
    # These are always shown in full; "other EMEA regional" Challengers
    # (_emea_order == 2) are demoted to the space-limited section below.
    emea = sorted(buckets["emea"], key=lambda m: _emea_order(m["event"]))
    emea_top = [m for m in emea if _emea_order(m["event"]) < 2]
    emea_regional = [m for m in emea if _emea_order(m["event"]) == 2]
    if emea_top:
        parts.append("\n⭐ <b>EMEA Challengers</b>")
        parts.extend(_format_match_line(m) for m in emea_top)

    # Everything below is part of a *summary*: it only fills the remaining
    # slots up to a target total number of matches, in strict priority order.
    # (HIGH + EMEA-top above are always shown in full, even if they already
    # exceed the target.)
    medium = sorted(buckets["medium"], key=lambda m: m["event"].lower())
    low = buckets["low"]

    optional_sections = [
        ("\n🌍 <b>Other EMEA Challengers</b>", emea_regional),
        ("\n⚡ <b>Medium Priority</b>", medium),
        ("\n💤 <b>Low Priority</b>", low),
    ]
    omitted = sum(len(matches) for _, matches in optional_sections)

    shown = len(high) + len(emea_top)
    remaining = max(0, _MAX_TOTAL_MATCHES - shown)
    for header, section_matches in optional_sections:
        if remaining <= 0:
            break
        header_added = False
        for match in section_matches:
            if remaining <= 0:
                break
            if not header_added:
                parts.append(header)
                header_added = True
            parts.append(_format_match_line(match))
            remaining -= 1
            omitted -= 1

    if omitted > 0:
        parts.append(f"\n<i>…and {omitted} more lower-priority match(es) omitted.</i>")

    return "\n".join(parts)
