# presentation_deck.py
# Build a deck-style briefing outline from a list of saved event dicts.
# Pure function — no I/O, no caching.

from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _first_sentence(text: str) -> str:
    """Return the first sentence of text, or full text truncated to 200 chars."""
    if not text:
        return ""
    for i, ch in enumerate(text):
        if ch in ".!?" and i >= 10:
            return text[: i + 1].strip()
    return text[:200].strip()


def _mode(values: list[str]) -> Optional[str]:
    """Most common non-None, non-empty value; None if list is empty."""
    filtered = [v for v in values if v]
    if not filtered:
        return None
    return Counter(filtered).most_common(1)[0][0]


def _entity_freq(evs: list[dict]) -> list[tuple[str, int]]:
    """Top-5 entities appearing ≥2 times across all beneficiaries + losers."""
    counts: Counter = Counter()
    for ev in evs:
        for entity in (ev.get("beneficiaries") or []) + (ev.get("losers") or []):
            if entity:
                counts[entity] += 1
    return [(e, c) for e, c in counts.most_common(5) if c >= 2]


def _top_ticker(tickers: list[dict]) -> Optional[dict]:
    """Ticker with the largest abs(return_1d); None if no usable tickers."""
    usable = [t for t in tickers if t.get("return_1d") is not None]
    if not usable:
        return None
    return max(usable, key=lambda t: abs(t["return_1d"]))


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _section_title(evs: list[dict], now: str) -> list[str]:
    lines = [
        "# Second Order — Briefing Deck",
        "",
        f"**Generated:** {now} UTC · **Analyses:** {len(evs)}",
        "",
        "---",
        "",
    ]
    return lines


def _section_executive_summary(evs: list[dict]) -> list[str]:
    lines = ["## Executive Summary", ""]
    high = [ev for ev in evs if ev.get("confidence") == "high"]
    sources = high if high else evs
    for ev in sources:
        sentence = _first_sentence(ev.get("what_changed") or "")
        lines.append(f"- **{ev.get('headline', 'Untitled')}** — {sentence}")
    lines.append("")

    # Shared signals — only shock type (stage is surfaced in Key Themes)
    shared = []
    common_shock = _mode([
        (ev.get("shock_decomposition") or {}).get("primary_label") or ""
        for ev in evs
    ])
    if common_shock:
        shared.append(common_shock)
    if shared:
        lines.append(f"**Shared signals:** {' · '.join(shared)}")
        lines.append("")
    return lines


def _section_key_themes(evs: list[dict]) -> list[str]:
    lines = ["## Key Themes", ""]
    has_content = False

    stages = list(dict.fromkeys(ev.get("stage") for ev in evs if ev.get("stage")))
    if stages:
        lines.append(f"- **Stages:** {', '.join(stages)}")
        has_content = True

    shocks = list(dict.fromkeys(
        (ev.get("shock_decomposition") or {}).get("primary_label")
        for ev in evs
        if (ev.get("shock_decomposition") or {}).get("primary_label")
    ))
    if shocks:
        lines.append(f"- **Shock types:** {', '.join(shocks)}")
        has_content = True

    regimes = list(dict.fromkeys(
        f"{ps['stance']} ({ps['regime']})"
        for ev in evs
        for ps in [(ev.get("policy_sensitivity") or {})]
        if ps.get("stance") and ps.get("regime")
    ))
    if regimes:
        lines.append(f"- **Policy regime:** {', '.join(regimes)}")
        has_content = True

    freq = _entity_freq(evs)
    if freq:
        entity_str = ", ".join(f"{e} ×{c}" for e, c in freq)
        lines.append(f"- **Recurring entities:** {entity_str}")
        has_content = True

    if not has_content:
        lines.append("*(no recurring signals detected)*")

    lines.append("")
    return lines


def _section_per_event(ev: dict, n: int) -> list[str]:
    lines = []
    headline = ev.get("headline", "Untitled")
    date = ev.get("event_date") or (ev.get("timestamp") or "")[:10]
    meta = " · ".join(filter(None, [
        date,
        ev.get("stage"),
        ev.get("persistence"),
        f"{ev['confidence']} confidence" if ev.get("confidence") else None,
    ]))
    lines.append(f"## {n}. {headline}")
    if meta:
        lines.append(f"**{meta}**")
    lines.append("")

    if ev.get("what_changed"):
        lines.append(f"- **Thesis:** {_first_sentence(ev['what_changed'])}")
    if ev.get("mechanism_summary"):
        lines.append(f"- **Mechanism:** {_first_sentence(ev['mechanism_summary'])}")

    bens = ev.get("beneficiaries") or []
    if bens:
        lines.append(f"- **Beneficiaries:** {', '.join(bens)}")

    losers = ev.get("losers") or []
    if losers:
        lines.append(f"- **Losers:** {', '.join(losers)}")

    ticker = _top_ticker(ev.get("market_tickers") or [])
    if ticker:
        r1 = ticker["return_1d"]
        sign = "+" if r1 >= 0 else ""
        tag = ticker.get("direction_tag") or "pending"
        lines.append(f"- **Top signal:** {ticker['symbol']} {sign}{r1:.2f}% (1d) — {tag}")

    ps = ev.get("policy_sensitivity") or {}
    if ps.get("stance") and ps.get("regime") and ps.get("explanation"):
        lines.append(
            f"- **Policy:** {ps['stance']} ({ps['regime']}) — "
            f"{_first_sentence(ps['explanation'])}"
        )

    sd = ev.get("shock_decomposition") or {}
    if sd.get("primary_label"):
        lines.append(f"- **Shock type:** {sd['primary_label']}")

    lines.append("")
    lines.append("---")
    lines.append("")
    return lines


def _section_risks(evs: list[dict]) -> list[str]:
    lines = ["## Risks & Watch Items", ""]

    all_losers: list[str] = []
    seen: set[str] = set()
    for ev in evs:
        for l in (ev.get("losers") or []):
            if l and l not in seen:
                seen.add(l)
                all_losers.append(l)
    if all_losers:
        lines.append(f"**Risks:** {', '.join(all_losers)}")

    watch_items: list[str] = []
    watch_seen: set[str] = set()
    for ev in evs:
        ip = ev.get("if_persists") or {}
        sub = ip.get("substitution")
        if sub and sub not in watch_seen:
            watch_seen.add(sub)
            watch_items.append(sub)
        for w in (ip.get("delayed_winners") or []) + (ip.get("delayed_losers") or []):
            if w and w not in watch_seen:
                watch_seen.add(w)
                watch_items.append(w)
    if watch_items:
        lines.append(f"**Watch:** {'; '.join(watch_items)}")

    revisit: list[str] = []
    for ev in evs:
        reasons = []
        if ev.get("persistence") == "persistent":
            reasons.append("persistent")
        if ev.get("rating") in ("mixed", "poor"):
            reasons.append(ev["rating"])
        if reasons:
            date = ev.get("event_date") or (ev.get("timestamp") or "")[:10]
            revisit.append(
                f"{ev.get('headline', 'Untitled')} ({date}) — {', '.join(reasons)}"
            )
    for r in revisit:
        lines.append(f"**Revisit:** {r}")

    lines.append("")
    return lines


def _section_closing(evs: list[dict]) -> list[str]:
    lines = ["## Closing", ""]
    has_content = False

    conviction = [
        ev for ev in evs
        if ev.get("confidence") == "high" and ev.get("rating") == "good"
    ]
    if conviction:
        for ev in conviction:
            conf = ev.get("confidence", "")
            rating = ev.get("rating", "")
            lines.append(f"**High conviction:** {ev.get('headline', 'Untitled')} ({conf}, {rating})")
        has_content = True

    loser_counts: Counter = Counter()
    for ev in evs:
        for l in (ev.get("losers") or []):
            if l:
                loser_counts[l] += 1
    top_losers = [l for l, _ in loser_counts.most_common(5)]
    if top_losers:
        lines.append(f"**Watch list:** {', '.join(top_losers)}")
        has_content = True

    binding = [
        ev for ev in evs
        if (ev.get("policy_constraint") or {}).get("binding")
    ]
    for ev in binding:
        bl = (ev.get("policy_constraint") or {}).get("binding_label", "binding")
        lines.append(f"**Policy binding:** {ev.get('headline', 'Untitled')} — {bl}")
        has_content = True

    if not has_content:
        lines.append("*(no high-conviction signals)*")

    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_presentation_deck(evs: list[dict]) -> str:
    """Build a presentation-style briefing deck in Markdown.

    Pure function — no I/O, no caching.
    evs : list of saved event dicts (same shape as load_event_by_id output)
    Returns: Markdown string with six fixed sections.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    lines: list[str] = []

    lines.extend(_section_title(evs, now))
    lines.extend(_section_executive_summary(evs))
    lines.extend(_section_key_themes(evs))
    for i, ev in enumerate(evs, 1):
        lines.extend(_section_per_event(ev, i))
    lines.extend(_section_risks(evs))
    lines.extend(_section_closing(evs))

    return "\n".join(lines)
