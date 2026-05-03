"""
tools/impact_label_audit.py

One-time audit of confidence (impact-level) label distribution and
downgrade-trigger frequency across events in the database.

Goal
----
Determine whether the scarcity of high-confidence events is real or a
calibration problem — i.e. events with strong analytical signals that
are being labelled medium or low for the wrong reasons.

What it reports
---------------
1. Distribution summary   — counts and % for high / medium / low
2. Signal scorecard       — per-event signals relevant to label ceiling
3. Barrier breakdown      — which downgrade barriers are most common
4. Near-high events       — medium events that satisfy all but one barrier
5. Confirmed-high events  — sanity-check: do current "high" events look right?
6. Low-signal stats       — why low_signal=1 events were flagged

Run
---
    python tools/impact_label_audit.py
    python tools/impact_label_audit.py --limit 200 --out report.md

The output is plain Markdown. Redirect to a file or read in stdout.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import init_db, load_recent_events


# ---------------------------------------------------------------------------
# Thresholds (mirrors analyze_event._validate_result — do not change here)
# ---------------------------------------------------------------------------

_CHAIN_MIN_FOR_HIGH = 3       # Rule 6
_MECH_MIN_LEN = 20            # Rule 1 / Rule 7
_INSUFFICIENT_PREFIX = "insufficient evidence"

# A "strong mechanism" heuristic for the near-high signal score.
# Not a production threshold — used only to surface candidates for review.
_STRONG_MECH_LEN = 80


# ---------------------------------------------------------------------------
# Per-event signal extraction
# ---------------------------------------------------------------------------

def _signals(ev: dict) -> dict:
    """Extract the signals that determine the label ceiling for one event."""
    confidence = (ev.get("confidence") or "low").lower().strip()
    stage      = (ev.get("stage") or "").lower().strip()
    mech       = (ev.get("mechanism_summary") or "").strip()
    chain      = ev.get("transmission_chain") or []
    bene       = ev.get("beneficiaries") or []
    lose       = ev.get("losers") or []
    btick      = ev.get("beneficiary_tickers") or []
    ltick      = ev.get("loser_tickers") or []
    mt         = ev.get("market_tickers") or []

    mech_len    = len(mech)
    chain_len   = len(chain) if isinstance(chain, list) else 0
    insuff      = _INSUFFICIENT_PREFIX in mech.lower()

    # Barriers to "high" label (mirrors _validate_result rules)
    barriers: list[str] = []
    if insuff:
        barriers.append("insufficient_evidence")
    if stage == "anticipation":
        barriers.append("anticipation_stage")
    if not btick or not ltick:
        parts = []
        if not btick:
            parts.append("no_btickers")
        if not ltick:
            parts.append("no_ltickers")
        barriers.append("+".join(parts))
    if chain_len < _CHAIN_MIN_FOR_HIGH:
        barriers.append(f"chain<{_CHAIN_MIN_FOR_HIGH}({chain_len})")
    if not bene and not lose:
        barriers.append("no_beneficiaries_or_losers")

    # "Near-high" score: 0–5 based on positive signals
    score = sum([
        bool(btick),
        bool(ltick),
        chain_len >= _CHAIN_MIN_FOR_HIGH,
        mech_len >= _STRONG_MECH_LEN,
        stage not in ("anticipation",) and not insuff,
    ])

    tickers_with_returns = [
        t for t in mt
        if isinstance(t, dict) and t.get("return_5d") is not None
    ]

    return {
        "id":           ev.get("id"),
        "headline":     (ev.get("headline") or "")[:90],
        "timestamp":    (ev.get("timestamp") or "")[:10],
        "confidence":   confidence,
        "stage":        stage,
        "mech_len":     mech_len,
        "chain_len":    chain_len,
        "n_btick":      len(btick),
        "n_ltick":      len(ltick),
        "n_bene":       len(bene),
        "n_lose":       len(lose),
        "insuff":       insuff,
        "low_signal":   bool(ev.get("low_signal")),
        "barriers":     barriers,
        "near_high_score": score,
        "mech_snippet": mech[:100],
        "n_returns":    len(tickers_with_returns),
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _bar(n: int, total: int, width: int = 20) -> str:
    filled = round(n / total * width) if total else 0
    return "#" * filled + "." * (width - filled)


def _row(*cells: str, widths: list[int] | None = None) -> str:
    if widths:
        parts = [str(c).ljust(w)[:w] for c, w in zip(cells, widths)]
    else:
        parts = [str(c) for c in cells]
    return "| " + " | ".join(parts) + " |"


def _divider(widths: list[int]) -> str:
    return "|" + "|".join("-" * (w + 2) for w in widths) + "|"


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def _section_distribution(rows: list[dict], out: list[str]) -> None:
    total = len(rows)
    by_label: dict[str, list[dict]] = {"high": [], "medium": [], "low": []}
    for r in rows:
        bucket = by_label.get(r["confidence"])
        if bucket is None:
            bucket = by_label.setdefault(r["confidence"], [])
        bucket.append(r)

    out.append("## 1. Label distribution\n")
    out.append(f"Total events audited: **{total}**\n")
    out.append("")
    w = [8, 6, 7, 22]
    out.append(_row("Label", "Count", "Pct", "Bar", widths=w))
    out.append(_divider(w))
    for label in ("high", "medium", "low"):
        n = len(by_label[label])
        pct = n / total * 100 if total else 0.0
        out.append(_row(
            label,
            str(n),
            f"{pct:.1f}%",
            _bar(n, total),
            widths=w,
        ))

    # Additional breakdown
    n_ls = sum(1 for r in rows if r["low_signal"])
    out.append("")
    out.append(f"- Events flagged `low_signal=1`: **{n_ls}** "
               f"({n_ls / total * 100:.1f}%)" if total else "")
    out.append("")


def _section_barriers(rows: list[dict], out: list[str]) -> None:
    from collections import Counter
    all_barriers: list[str] = []
    for r in rows:
        all_barriers.extend(r["barriers"])

    medium_barriers: list[str] = []
    for r in rows:
        if r["confidence"] == "medium":
            medium_barriers.extend(r["barriers"])

    out.append("## 2. Barrier frequency\n")
    out.append("How often each 'ceiling barrier' appears across all events "
               "(a barrier means the event can't reach high without fixing it).\n")
    w = [36, 9, 12, 22]
    out.append(_row("Barrier", "All", "Medium only", "Bar (medium)", widths=w))
    out.append(_divider(w))
    cnt_all = Counter(all_barriers)
    cnt_med = Counter(medium_barriers)
    total   = len(rows)
    for barrier, n_all in cnt_all.most_common():
        n_med = cnt_med.get(barrier, 0)
        out.append(_row(
            barrier,
            str(n_all),
            str(n_med),
            _bar(n_med, total),
            widths=w,
        ))
    if not all_barriers:
        out.append("*(no barriers found — all events already qualify for high)*")
    out.append("")


def _section_near_high(rows: list[dict], out: list[str]) -> None:
    """Medium events with exactly one barrier — easiest to promote."""
    candidates = [
        r for r in rows
        if r["confidence"] == "medium" and len(r["barriers"]) == 1
    ]
    candidates.sort(key=lambda r: -r["near_high_score"])

    out.append("## 3. Near-high events (medium, one barrier)\n")
    out.append(
        f"{len(candidates)} medium-confidence events have exactly one barrier "
        "to high. These are the most likely calibration candidates.\n"
    )
    if not candidates:
        out.append("*(none)*\n")
        return

    w = [5, 10, 5, 5, 5, 5, 38]
    out.append(_row("ID", "Date", "Sc", "Ch", "BT", "LT", "Barrier", widths=w))
    out.append(_divider(w))
    for r in candidates[:40]:
        out.append(_row(
            str(r["id"]),
            r["timestamp"],
            str(r["near_high_score"]),
            str(r["chain_len"]),
            str(r["n_btick"]),
            str(r["n_ltick"]),
            r["barriers"][0],
            widths=w,
        ))
    if len(candidates) > 40:
        out.append(f"\n*(+ {len(candidates) - 40} more not shown)*")
    out.append("")

    # Sample headlines for top 10
    out.append("### Sample headlines (top 10 by signal score)\n")
    for r in candidates[:10]:
        b = r["barriers"][0]
        hl = r["headline"]
        out.append(f"- **[{r['id']}]** `{b}` — {hl}")
    out.append("")


def _section_zero_barrier_medium(rows: list[dict], out: list[str]) -> None:
    """Medium events with NO barriers — LLM assigned medium, rules didn't downgrade."""
    candidates = [
        r for r in rows
        if r["confidence"] == "medium" and len(r["barriers"]) == 0
    ]
    candidates.sort(key=lambda r: -r["near_high_score"])

    out.append("## 4. LLM-assigned medium (zero barriers)\n")
    out.append(
        f"{len(candidates)} medium-confidence events pass all downgrade rules "
        "— the LLM itself chose medium. These are the strongest calibration signal.\n"
    )
    if not candidates:
        out.append("*(none)*\n")
        return

    w = [5, 10, 5, 5, 5, 5, 90]
    out.append(_row("ID", "Date", "Sc", "Ch", "BT", "LT", "Headline (truncated)", widths=w))
    out.append(_divider(w))
    for r in candidates[:30]:
        out.append(_row(
            str(r["id"]),
            r["timestamp"],
            str(r["near_high_score"]),
            str(r["chain_len"]),
            str(r["n_btick"]),
            str(r["n_ltick"]),
            r["headline"],
            widths=w,
        ))
    if len(candidates) > 30:
        out.append(f"\n*(+ {len(candidates) - 30} more)*")
    out.append("")


def _section_confirmed_high(rows: list[dict], out: list[str]) -> None:
    high = [r for r in rows if r["confidence"] == "high"]
    high.sort(key=lambda r: r["timestamp"], reverse=True)

    out.append("## 5. Confirmed-high events\n")
    out.append(f"{len(high)} events are labelled high confidence.\n")
    if not high:
        out.append("*(none — this is the calibration problem)*\n")
        return

    w = [5, 10, 5, 5, 5, 5, 90]
    out.append(_row("ID", "Date", "Ch", "BT", "LT", "Ret", "Headline", widths=w))
    out.append(_divider(w))
    for r in high:
        out.append(_row(
            str(r["id"]),
            r["timestamp"],
            str(r["chain_len"]),
            str(r["n_btick"]),
            str(r["n_ltick"]),
            str(r["n_returns"]),
            r["headline"],
            widths=w,
        ))
    out.append("")


def _section_signal_scorecard(rows: list[dict], out: list[str]) -> None:
    """Aggregate signal quality by label."""
    import statistics

    def _stats(values: list[float]) -> str:
        if not values:
            return "n/a"
        return f"avg {statistics.mean(values):.1f}, med {statistics.median(values):.1f}"

    out.append("## 6. Signal quality scorecard\n")
    out.append("Average signal quality for events in each confidence bucket.\n")

    cols = ["Metric", "high", "medium", "low"]
    w = [28, 20, 20, 20]
    out.append(_row(*cols, widths=w))
    out.append(_divider(w))

    def _col(label: str, fn):
        vals = {k: [fn(r) for r in rows if r["confidence"] == k] for k in ("high", "medium", "low")}
        return _row(label, _stats(vals["high"]), _stats(vals["medium"]), _stats(vals["low"]), widths=w)

    out.append(_col("mechanism length (chars)", lambda r: r["mech_len"]))
    out.append(_col("chain length (steps)", lambda r: r["chain_len"]))
    out.append(_col("beneficiary tickers", lambda r: r["n_btick"]))
    out.append(_col("loser tickers", lambda r: r["n_ltick"]))
    out.append(_col("tickers with 5d returns", lambda r: r["n_returns"]))
    out.append(_col("near-high signal score (0-5)", lambda r: r["near_high_score"]))
    out.append("")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Ensure stdout handles UTF-8 on Windows (cp1252 default drops special chars).
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Impact label audit")
    parser.add_argument("--limit", type=int, default=500,
                        help="Max events to load (default 500)")
    parser.add_argument("--out", type=str, default=None,
                        help="Write report to FILE in addition to stdout")
    args = parser.parse_args()

    init_db()
    events = load_recent_events(args.limit)
    rows   = [_signals(ev) for ev in events]

    out: list[str] = []
    out.append("# Impact Label Audit\n")
    out.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    out.append(f"Events loaded: {len(rows)} (limit={args.limit})\n")
    out.append("")
    out.append("**Column key:** Sc=near-high score (0-5), Ch=chain steps, "
               "BT=beneficiary tickers, LT=loser tickers, Ret=tickers with 5d returns\n")
    out.append("")

    _section_distribution(rows, out)
    _section_barriers(rows, out)
    _section_near_high(rows, out)
    _section_zero_barrier_medium(rows, out)
    _section_confirmed_high(rows, out)
    _section_signal_scorecard(rows, out)

    report = "\n".join(out)
    print(report)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nReport written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
