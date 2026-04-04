# app.py — Second Order V1.5
# Streamlit UI.  Run with: streamlit run app.py
#
# Design references
# -  Semafor Signals: facts-first story structure, calm editorial tone
# -  Ground News: clustered multi-source scanning, source comparison
# -  BlackRock Geopolitical Risk Dashboard: event-to-market risk framing

import streamlit as st
from datetime import datetime

from classify import classify_stage, classify_persistence
from analyze_event import analyze_event, is_mock
from market_check import market_check as run_market_check, followup_check
from db import (init_db, save_event, load_recent_events,
                find_related_events, update_review)
from news_sources import fetch_all, cluster_headlines, source_tier

# ---------------------------------------------------------------------------
# CSS — editorial palette, no trader-terminal colours
# ---------------------------------------------------------------------------

_CSS = """
<style>
/* ── Typography ─────────────────────────────────────────────────── */
html, body, [class*="css"] { font-family: "Inter", system-ui, -apple-system, sans-serif; }

/* ── Muted section dividers ─────────────────────────────────────── */
.sec-rule { border: none; border-top: 1px solid #e5e7eb; margin: 28px 0 20px 0; }

/* ── Section heading — Semafor-style all-caps kicker ────────────── */
.sec-head {
    font-size: 0.65rem; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; color: #6b7280; margin-bottom: 12px;
}

/* ── Badges — muted pastels, not neon ───────────────────────────── */
.tag {
    display: inline-block; padding: 2px 8px; border-radius: 3px;
    font-size: 0.72rem; font-weight: 600; letter-spacing: 0.015em;
    line-height: 1.55; vertical-align: middle;
}
.tag-blue   { background: #eff6ff; color: #1e40af; }
.tag-green  { background: #f0fdf4; color: #166534; }
.tag-amber  { background: #fffbeb; color: #92400e; }
.tag-red    { background: #fef2f2; color: #991b1b; }
.tag-violet { background: #f5f3ff; color: #5b21b6; }
.tag-slate  { background: #f1f5f9; color: #475569; }

/* ── Source pills (Ground News style) ───────────────────────────── */
.src-pill {
    display: inline-block; padding: 1px 7px; border-radius: 3px;
    font-size: 0.68rem; font-weight: 600; margin-right: 3px;
    vertical-align: middle;
}
.src-high   { background: #f0fdf4; color: #166534; }
.src-mid    { background: #fffbeb; color: #92400e; }
.src-low    { background: #f1f5f9; color: #64748b; }

/* ── Story card — the primary content container ─────────────────── */
.story {
    background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
    padding: 20px 24px 16px 24px; margin-bottom: 14px;
}
.story-headline {
    font-size: 1.0rem; font-weight: 700; color: #111827;
    line-height: 1.38; margin-bottom: 6px;
}
.story-body {
    font-size: 0.87rem; color: #374151; line-height: 1.6; margin-top: 6px;
}
.story-meta {
    font-size: 0.70rem; color: #9ca3af; line-height: 1.45;
}

/* ── Kicker labels inside cards ─────────────────────────────────── */
.kicker {
    font-size: 0.63rem; font-weight: 700; letter-spacing: 0.10em;
    text-transform: uppercase; color: #9ca3af; margin-bottom: 4px;
}

/* ── Evidence rows (Ground News source-comparison) ──────────────── */
.ev-row {
    font-size: 0.78rem; color: #4b5563; padding: 4px 0; line-height: 1.5;
    border-bottom: 1px solid #f3f4f6;
}
.ev-row:last-child { border-bottom: none; }
.ev-src  { font-weight: 600; color: #374151; }
.ev-ts   { color: #9ca3af; font-size: 0.72rem; }
.ev-note { color: #b45309; font-style: italic; font-size: 0.75rem; }

/* ── Market exposure panel (BlackRock risk-dashboard feel) ───────── */
.mkt-panel {
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 18px 22px 14px 22px; margin-top: 12px;
}
.mkt-table { width: 100%; border-collapse: collapse; font-size: 0.83rem; }
.mkt-table th {
    text-align: left; font-size: 0.63rem; text-transform: uppercase;
    letter-spacing: 0.08em; color: #94a3b8; font-weight: 700;
    padding: 4px 10px 5px 0; border-bottom: 1px solid #e2e8f0;
}
.mkt-table td { padding: 5px 10px 5px 0; border-bottom: 1px solid #f1f5f9; }
.mkt-sym  { font-weight: 700; color: #0f172a; }
.mkt-role { font-size: 0.75rem; color: #64748b; }
.mkt-pos  { color: #15803d; font-weight: 600; }
.mkt-neg  { color: #b91c1c; font-weight: 600; }
.mkt-na   { color: #94a3b8; }

/* Hypothesis-support verdict */
.verdict {
    display: inline-block; padding: 5px 12px; border-radius: 4px;
    font-size: 0.80rem; font-weight: 600; margin-top: 10px;
}
.verdict-strong   { background: #f0fdf4; color: #166534; }
.verdict-moderate { background: #fffbeb; color: #92400e; }
.verdict-weak     { background: #fef2f2; color: #991b1b; }
.verdict-neutral  { background: #f1f5f9; color: #475569; }

/* ── Saved-analysis list card ───────────────────────────────────── */
.sa-card {
    background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
    padding: 16px 20px 12px 20px; margin-bottom: 10px;
}
.sa-hl {
    font-size: 0.92rem; font-weight: 700; color: #111827; line-height: 1.38;
}
.sa-mech {
    font-size: 0.82rem; color: #4b5563; line-height: 1.5; margin-top: 5px;
}
.sa-ts { font-size: 0.68rem; color: #94a3b8; }

/* ── Research note display ──────────────────────────────────────── */
.note-block {
    font-size: 0.82rem; color: #374151; line-height: 1.55;
    background: #f8fafc; border-left: 3px solid #cbd5e1;
    padding: 10px 14px; border-radius: 0 6px 6px 0; margin-top: 8px;
}

/* ── Related events timeline ────────────────────────────────────── */
.rel-item {
    font-size: 0.78rem; color: #4b5563; line-height: 1.5;
    padding: 4px 0 4px 12px; border-left: 2px solid #e2e8f0;
    margin-bottom: 2px;
}
.rel-ts { color: #94a3b8; font-size: 0.72rem; }

/* ── Follow-up table ────────────────────────────────────────────── */
.fu-table { width: 100%; border-collapse: collapse; font-size: 0.80rem; }
.fu-table th {
    text-align: left; font-size: 0.62rem; text-transform: uppercase;
    letter-spacing: 0.08em; color: #94a3b8; font-weight: 700;
    padding: 3px 8px 4px 0; border-bottom: 1px solid #e2e8f0;
}
.fu-table td { padding: 4px 8px 4px 0; border-bottom: 1px solid #f1f5f9; }

/* ── Empty states ───────────────────────────────────────────────── */
.empty {
    text-align: center; padding: 36px 20px; color: #94a3b8;
    font-size: 0.86rem; line-height: 1.6;
}
.empty b { color: #64748b; }

/* ── Streamlit overrides ────────────────────────────────────────── */
div[data-testid="stMetric"] {
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;
    padding: 10px 14px 6px 14px;
}
</style>
"""

# ---------------------------------------------------------------------------
# Helpers — badge builders
# ---------------------------------------------------------------------------

_STAGE_MAP  = {"anticipation": "blue", "realized": "green", "escalation": "red",
               "de-escalation": "violet", "normalization": "slate"}
_PERS_MAP   = {"transient": "slate", "medium": "amber", "structural": "violet"}
_CONF_MAP   = {"low": "red", "medium": "amber", "high": "green"}
_RATING_MAP = {"good": "green", "mixed": "amber", "poor": "red"}

def _tag(text: str, colour: str) -> str:
    return f'<span class="tag tag-{colour}">{text}</span>'

def _stage_tag(s: str) -> str:   return _tag(s, _STAGE_MAP.get(s, "slate"))
def _pers_tag(p: str) -> str:    return _tag(p, _PERS_MAP.get(p, "slate"))
def _conf_tag(c: str) -> str:    return _tag(c, _CONF_MAP.get(c, "slate"))
def _rating_tag(r: str) -> str:  return _tag(r, _RATING_MAP.get(r, "slate")) if r else ""

def _src_pills(sources: list[dict]) -> str:
    tier_cls = {"high": "src-high", "medium": "src-mid", "low": "src-low"}
    return "".join(
        f'<span class="src-pill {tier_cls.get(s["tier"], "src-low")}">{s["name"]}</span>'
        for s in sources
    )

def _dir_label(tag: str | None) -> str:
    """Plain-text direction label, no emoji-heavy trader style."""
    if not tag:
        return "—"
    return f'<span class="mkt-pos">Supports</span>' if tag.startswith("supports") \
        else f'<span class="mkt-neg">Against</span>'


# ---------------------------------------------------------------------------
# LLM context builder (unchanged logic)
# ---------------------------------------------------------------------------

def _build_event_context(cluster: dict) -> str:
    con = cluster.get("consensus", {})
    lines: list[str] = []
    if con:
        lines.append("Structured event context:")
        if con.get("actors"):
            lines.append(f"  Actors: {', '.join(con['actors'])}")
        if con.get("action") and con["action"] != "unknown":
            lines.append(f"  Action: {con['action']}")
        if con.get("geography"):
            lines.append(f"  Geography: {', '.join(con['geography'])}")
        if con.get("sector") and con["sector"] != "unknown":
            lines.append(f"  Sector: {con['sector']}")
        lines.append(f"  Uncertainty: {con.get('uncertainty', 'high')}")
        lines.append(f"  Consensus: {con.get('consensus', 'mixed')}")
    if cluster["source_count"] > 1:
        lines.append("")
        lines.append("Multi-source context:")
        lines.append(f"  Summary: {cluster['summary']}")
        sp = [f"{s['name']} ({s['tier']} tier)" for s in cluster["sources"]]
        lines.append(f"  Sources ({cluster['source_count']}): {', '.join(sp)}")
        lines.append(f"  Source agreement: {cluster['agreement']}")
        if cluster["agreement"] == "mixed":
            lines.append(
                "  Note: sources frame this event differently. "
                "Weigh the higher-tier account more heavily, but acknowledge "
                "the disagreement in your analysis if it affects the mechanism."
            )
    return ("\n".join(lines) + "\n") if lines else ""


# ---------------------------------------------------------------------------
# Market-exposure HTML builders (BlackRock-style risk panel)
# ---------------------------------------------------------------------------

def _mkt_table(tickers: list[dict]) -> str:
    """Compact asset-exposure table."""
    if not tickers:
        return ""
    rows = []
    for t in tickers:
        r5 = t.get("return_5d")
        r5_s = f"{r5:+.1f}%" if r5 is not None else "—"
        r5_c = "mkt-na" if r5 is None else ("mkt-pos" if r5 >= 0 else "mkt-neg")
        dtag = t.get("direction_tag") or ""
        d = _dir_label(dtag)
        role = t.get("role", "")
        arrow = "↑" if role == "beneficiary" else ("↓" if role == "loser" else "")
        rows.append(
            f'<tr><td><span class="mkt-sym">{t["symbol"]}</span></td>'
            f'<td><span class="mkt-role">{arrow} {role}</span></td>'
            f'<td><span class="{r5_c}">{r5_s}</span></td>'
            f'<td>{t.get("label","—")}</td><td>{d}</td></tr>'
        )
    return (
        '<table class="mkt-table">'
        '<tr><th>Asset</th><th>Exposure</th><th>5-day</th>'
        '<th>Signal</th><th>Versus hypothesis</th></tr>'
        + "".join(rows) + '</table>'
    )


def _verdict_html(note: str) -> str:
    """Extract hypothesis-support line from market note, render as verdict bar."""
    for ln in reversed(note.splitlines()):
        if "Hypothesis support" in ln:
            text = ln.strip()
            low = text.lower()
            if "strong" in low:    cls = "verdict-strong"
            elif "moderate" in low: cls = "verdict-moderate"
            elif "weak" in low:    cls = "verdict-weak"
            else:                  cls = "verdict-neutral"
            return f'<div class="verdict {cls}">{text}</div>'
    return ""


# ---------------------------------------------------------------------------
# _render_result — Semafor-style facts → analysis → market exposure
# ---------------------------------------------------------------------------

def _render_result(analysis: dict, market: dict, stage: str,
                   persistence: str, event_date: str | None) -> None:

    mock = "[mock:" in (analysis.get("what_changed") or "")
    if mock:
        st.warning(
            "Placeholder data — set ANTHROPIC_API_KEY in .env for real analysis."
        )

    # ── 1. Classification strip ──
    st.markdown(
        f'<div style="margin:10px 0 14px 0">'
        f'{_stage_tag(stage)} &nbsp; {_pers_tag(persistence)} &nbsp; '
        f'{_conf_tag(analysis["confidence"])}'
        f'</div>',
        unsafe_allow_html=True,
    )

    if analysis.get("validation_warnings"):
        st.warning(" · ".join(analysis["validation_warnings"]))

    # ── 2. The Facts (Semafor "Semafor" block) ──
    st.markdown(
        f'<div class="story">'
        f'<div class="kicker">THE FACTS</div>'
        f'<div class="story-body">{analysis["what_changed"]}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── 3. The Mechanism (Semafor "Know More" / analysis block) ──
    st.markdown(
        f'<div class="story">'
        f'<div class="kicker">THE MECHANISM</div>'
        f'<div class="story-body">{analysis["mechanism_summary"]}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── 4. Exposed sectors — two columns ──
    col_b, col_l = st.columns(2)
    with col_b:
        items = "".join(f"<li>{b}</li>" for b in analysis["beneficiaries"])
        up = analysis["beneficiary_tickers"]
        up_line = (
            f'<div style="margin-top:8px;font-size:0.78rem;color:#15803d;font-weight:600">'
            f'Tickers: {"  ·  ".join(up)}</div>' if up
            else '<div style="margin-top:8px;font-size:0.76rem;color:#94a3b8">No tickers identified</div>'
        )
        st.markdown(
            f'<div class="story" style="border-top:3px solid #bbf7d0">'
            f'<div class="kicker">POTENTIAL BENEFICIARIES</div>'
            f'<ul style="margin:4px 0 2px 18px;padding:0;font-size:0.85rem;'
            f'color:#1f2937;line-height:1.65">{items}</ul>{up_line}</div>',
            unsafe_allow_html=True,
        )
    with col_l:
        items = "".join(f"<li>{lo}</li>" for lo in analysis["losers"])
        dn = analysis["loser_tickers"]
        dn_line = (
            f'<div style="margin-top:8px;font-size:0.78rem;color:#b91c1c;font-weight:600">'
            f'Tickers: {"  ·  ".join(dn)}</div>' if dn
            else '<div style="margin-top:8px;font-size:0.76rem;color:#94a3b8">No tickers identified</div>'
        )
        st.markdown(
            f'<div class="story" style="border-top:3px solid #fecaca">'
            f'<div class="kicker">POTENTIAL LOSERS</div>'
            f'<ul style="margin:4px 0 2px 18px;padding:0;font-size:0.85rem;'
            f'color:#1f2937;line-height:1.65">{items}</ul>{dn_line}</div>',
            unsafe_allow_html=True,
        )

    # ── 5. Market exposure panel (BlackRock style) ──
    st.markdown('<div class="mkt-panel"><div class="kicker">MARKET EXPOSURE CHECK</div>',
                unsafe_allow_html=True)
    if event_date:
        anchor = market.get("anchor_date")
        note = f"Anchored to {event_date}"
        if anchor and anchor != event_date:
            note += f" (first trading day: {anchor})"
        st.caption(note)
    else:
        st.caption("Rolling window — not anchored to a specific event date.")

    tbl = _mkt_table(market["tickers"])
    if tbl:
        st.markdown(tbl, unsafe_allow_html=True)
    else:
        st.caption("No assets to check.")

    v = _verdict_html(market["note"])
    if v:
        st.markdown(v, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# _run_analysis — pipeline orchestrator (logic unchanged)
# ---------------------------------------------------------------------------

def _run_analysis(headline: str, event_date_input,
                  event_context: str = "") -> dict:
    stage       = classify_stage(headline)
    persistence = classify_persistence(headline)
    analysis    = analyze_event(headline, stage, persistence,
                                event_context=event_context)
    event_date  = event_date_input.strftime("%Y-%m-%d") if event_date_input else None
    market      = run_market_check(
        analysis["beneficiary_tickers"],
        analysis["loser_tickers"],
        event_date=event_date,
    )
    if is_mock(analysis):
        st.info("Mock analysis — result not saved.")
    else:
        try:
            save_event({
                "timestamp":         datetime.now().isoformat(timespec="seconds"),
                "headline":          headline,
                "stage":             stage,
                "persistence":       persistence,
                "what_changed":      analysis["what_changed"],
                "mechanism_summary": analysis["mechanism_summary"],
                "beneficiaries":     analysis["beneficiaries"],
                "losers":            analysis["losers"],
                "assets_to_watch":   analysis["assets_to_watch"],
                "confidence":        analysis["confidence"],
                "market_note":       market["note"],
                "market_tickers":    market["tickers"],
                "event_date":        event_date,
                "notes":             "",
            })
        except Exception as e:
            st.error(f"Could not save event: {e}")
    return {"stage": stage, "persistence": persistence,
            "analysis": analysis, "market": market, "event_date": event_date}


# ═══════════════════════════════════════════════════════════════════════════
# Page setup
# ═══════════════════════════════════════════════════════════════════════════

init_db()
st.set_page_config(page_title="Second Order", page_icon="🌍", layout="centered")
st.markdown(_CSS, unsafe_allow_html=True)

# ── Masthead ──
st.markdown(
    '<div style="margin-bottom:2px">'
    '<span style="font-size:1.45rem;font-weight:800;letter-spacing:-0.02em;'
    'color:#0f172a">Second Order</span></div>'
    '<div style="font-size:0.84rem;color:#64748b;line-height:1.5;'
    'margin-bottom:6px">'
    'Geopolitical event analysis — surface hidden economic mechanisms, '
    'map exposed sectors, validate against market data.</div>',
    unsafe_allow_html=True,
)

if "active_idx" not in st.session_state:
    st.session_state.active_idx = None
if "active_result" not in st.session_state:
    st.session_state.active_result = None


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — Signals (News Inbox)
# ═══════════════════════════════════════════════════════════════════════════

st.markdown('<hr class="sec-rule">', unsafe_allow_html=True)
st.markdown('<div class="sec-head">Signals</div>', unsafe_allow_html=True)

col_date, _ = st.columns([1, 2])
with col_date:
    event_date_input = st.date_input(
        "Event date (optional)",
        value=None,
        help="Anchor market returns to this date instead of the rolling window.",
    )

@st.cache_data(ttl=600, show_spinner="Fetching headlines…")
def _cached_fetch():
    records, feed_status = fetch_all()
    return cluster_headlines(records), feed_status

inbox_clusters, feed_status = _cached_fetch()

# Feed health — secondary, calm status line
if feed_status:
    ok_feeds    = [f for f in feed_status if f["ok"]]
    failed      = [f["name"] for f in feed_status if not f["ok"]]
    total       = len(feed_status)
    if failed:
        ok_names = ", ".join(f["name"] for f in ok_feeds) if ok_feeds else "none"
        offline_part = " · offline: " + ", ".join(failed)
        st.markdown(
            f'<div style="font-size:0.70rem;color:#94a3b8;margin:-4px 0 8px 0">'
            f'{len(ok_feeds)}/{total} feeds active ({ok_names}){offline_part}'
            f'</div>',
            unsafe_allow_html=True,
        )

if not inbox_clusters:
    st.markdown(
        '<div class="empty">'
        'No signals available.<br>'
        '<b>Add entries to <code>news_inbox.json</code></b> or check RSS connectivity.'
        '</div>',
        unsafe_allow_html=True,
    )
else:
    for idx, cluster in enumerate(inbox_clusters[:15]):
        pub = cluster["published_at"][:16].replace("T", " ") if cluster["published_at"] else ""
        is_active = (st.session_state.active_idx == idx)

        col_text, col_btn = st.columns([6, 1])

        with col_text:
            # Source pills
            pills = _src_pills(cluster["sources"])
            mixed_note = (
                '<span style="font-size:0.68rem;color:#b45309;margin-left:4px">'
                '— framing differs</span>'
                if cluster["agreement"] == "mixed" else ""
            )
            ts_bit = (f' <span style="font-size:0.68rem;color:#94a3b8">'
                       f'· {pub}</span>') if pub else ""

            # Headline card
            st.markdown(
                f'<div class="story" style="padding:14px 18px 10px 18px;'
                f'margin-bottom:4px">'
                f'<div class="story-headline">{cluster["headline"]}</div>'
                f'<div class="story-meta">{pills}{mixed_note}{ts_bit}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # Cluster summary (multi-source only)
            if cluster["source_count"] > 1 and cluster.get("summary"):
                st.caption(cluster["summary"])

            # Source-comparison panel (Ground News style)
            evidence = cluster.get("evidence", [])
            if len(evidence) > 1:
                ev_html = ['<div style="margin:2px 0 6px 0">'
                           '<div class="kicker">SOURCE COMPARISON</div>']
                for ev in evidence:
                    ts = (ev["published_at"] or "")[:16].replace("T", " ")
                    tier_dot = {"high": "🟢", "medium": "🟡", "low": "⚪"}.get(
                        ev["tier"], "⚪")
                    title = ev["title"][:100] + ("…" if len(ev["title"]) > 100 else "")
                    note = (f'<br><span class="ev-note">{ev["note"]}</span>'
                            if ev.get("note") else "")
                    ev_html.append(
                        f'<div class="ev-row">'
                        f'{tier_dot} <span class="ev-src">{ev["source"]}</span> '
                        f'<span class="ev-ts">· {ts}</span><br>{title}{note}</div>'
                    )
                ev_html.append('</div>')
                st.markdown("".join(ev_html), unsafe_allow_html=True)

        with col_btn:
            label = "Close" if is_active else "Analyze"
            if st.button(label, key=f"inbox_{idx}", use_container_width=True):
                if is_active:
                    st.session_state.active_idx = None
                    st.session_state.active_result = None
                else:
                    st.session_state.active_idx = idx
                    st.session_state.active_result = None
                st.rerun()

        # Inline analysis
        if is_active:
            headline = cluster["headline"].strip()[:500]
            cached = st.session_state.active_result
            cached_date = cached["event_date"] if cached else None
            current_date = event_date_input.strftime("%Y-%m-%d") if event_date_input else None
            if cached is None or cached_date != current_date:
                ctx = _build_event_context(cluster)
                with st.spinner("Analyzing…"):
                    st.session_state.active_result = _run_analysis(
                        headline, event_date_input, event_context=ctx)

            res = st.session_state.active_result
            _render_result(res["analysis"], res["market"],
                           res["stage"], res["persistence"], res["event_date"])
            st.markdown('<hr class="sec-rule">', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — Analysis Archive
# ═══════════════════════════════════════════════════════════════════════════

st.markdown('<hr class="sec-rule">', unsafe_allow_html=True)
st.markdown('<div class="sec-head">Analysis Archive</div>', unsafe_allow_html=True)

events = load_recent_events(25)

if not events:
    st.markdown(
        '<div class="empty">'
        'No analyses saved yet.<br>'
        '<b>Run an analysis above</b> to start building your archive.'
        '</div>',
        unsafe_allow_html=True,
    )
else:
    # ── Integrated filter bar ──
    fc1, fc2, fc3 = st.columns([1.2, 1.2, 3])
    with fc1:
        f_rating = st.selectbox(
            "Rating", ["all", "good", "mixed", "poor", "unreviewed"],
            key="f_rating", label_visibility="collapsed",
        )
    with fc2:
        f_stage = st.selectbox(
            "Stage",
            ["all"] + list(_STAGE_MAP.keys()),
            key="f_stage", label_visibility="collapsed",
        )
    with fc3:
        f_q = st.text_input(
            "Search", key="f_q", placeholder="Search headlines or mechanisms…",
            label_visibility="collapsed",
        )

    # Apply
    vis = events
    if f_rating != "all":
        vis = ([e for e in vis if not e.get("rating")] if f_rating == "unreviewed"
               else [e for e in vis if e.get("rating") == f_rating])
    if f_stage != "all":
        vis = [e for e in vis if e.get("stage") == f_stage]
    if f_q:
        q = f_q.lower()
        vis = [e for e in vis if q in e["headline"].lower()
               or q in (e.get("mechanism_summary") or "").lower()]

    reviewed = sum(1 for e in events if e.get("rating"))
    st.markdown(
        f'<div style="font-size:0.72rem;color:#94a3b8;margin:0 0 10px 0">'
        f'Showing {len(vis)} of {len(events)} · {reviewed} reviewed</div>',
        unsafe_allow_html=True,
    )

    if not vis:
        st.markdown(
            '<div class="empty" style="padding:20px">No events match these filters.</div>',
            unsafe_allow_html=True,
        )

    for e in vis:
        eid = e["id"]
        rating = e.get("rating") or ""
        ts = (e.get("timestamp") or "")[:16].replace("T", " ")
        hl = e["headline"][:130] + ("…" if len(e["headline"]) > 130 else "")
        mech = e.get("mechanism_summary") or ""
        mech_short = mech[:220] + ("…" if len(mech) > 220 else "")

        # Tags line
        tags = f'{_stage_tag(e["stage"])} &nbsp; {_pers_tag(e["persistence"])}'
        tags += f' &nbsp; {_conf_tag(e["confidence"])}'
        if rating:
            tags += f' &nbsp; {_rating_tag(rating)}'

        # Card
        card = (
            f'<div class="sa-card">'
            f'<div class="sa-hl">{hl}</div>'
            f'<div style="margin:5px 0 3px 0">{tags}</div>'
            f'<div class="sa-ts">{ts}'
        )
        if e.get("event_date"):
            card += f' · anchored to {e["event_date"]}'
        card += '</div>'
        if mech_short:
            card += f'<div class="sa-mech">{mech_short}</div>'

        # Show existing research note inline on card
        notes = e.get("notes") or ""
        if notes:
            card += (f'<div class="note-block" style="margin-top:8px">'
                     f'{notes}</div>')
        card += '</div>'
        st.markdown(card, unsafe_allow_html=True)

        # ── Detail expander ──
        with st.expander("View full analysis", expanded=False):

            # Full mechanism (if truncated above)
            if mech and len(mech) > 220:
                st.markdown(
                    f'<div class="story">'
                    f'<div class="kicker">FULL MECHANISM</div>'
                    f'<div class="story-body">{mech}</div></div>',
                    unsafe_allow_html=True,
                )

            # Market exposure
            saved_tickers = e.get("market_tickers", [])
            if saved_tickers:
                st.markdown('<div class="mkt-panel">'
                            '<div class="kicker">MARKET EXPOSURE</div>',
                            unsafe_allow_html=True)
                st.markdown(_mkt_table(saved_tickers), unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            # Follow-up outcomes
            saved_event_date = e.get("event_date")
            if saved_event_date and saved_tickers:
                followup = followup_check(saved_tickers, saved_event_date)
                if followup:
                    fu_anchor = next(
                        (fu.get("anchor_date") for fu in followup
                         if fu.get("anchor_date")), None)
                    lbl = "FOLLOW-UP"
                    if fu_anchor and fu_anchor != saved_event_date:
                        lbl += f" · anchor: {fu_anchor}"
                    fu_rows = []
                    for fu in followup:
                        r1  = f"{fu['return_1d']:+.1f}%" if fu["return_1d"]  is not None else "—"
                        r5  = f"{fu['return_5d']:+.1f}%" if fu["return_5d"]  is not None else "—"
                        r20 = f"{fu['return_20d']:+.1f}%" if fu["return_20d"] is not None else "—"
                        d   = _dir_label(fu.get("direction"))
                        arrow = "↑" if fu["role"] == "beneficiary" else "↓"
                        fu_rows.append(
                            f'<tr><td><b>{fu["symbol"]}</b></td>'
                            f'<td>{arrow} {fu["role"]}</td>'
                            f'<td>{r1}</td><td>{r5}</td><td>{r20}</td>'
                            f'<td>{d}</td></tr>'
                        )
                    st.markdown(
                        f'<div class="kicker">{lbl}</div>'
                        f'<table class="fu-table">'
                        f'<tr><th>Asset</th><th>Exposure</th><th>1d</th>'
                        f'<th>5d</th><th>20d</th><th>Direction</th></tr>'
                        f'{"".join(fu_rows)}</table>',
                        unsafe_allow_html=True,
                    )
            elif not saved_event_date and saved_tickers:
                st.caption("No event date — follow-up returns unavailable.")

            # Related events
            related = find_related_events(e["id"], e["headline"], limit=5)
            if related:
                rel_rows = []
                for rel in related:
                    rel_ts = (rel.get("timestamp") or "")[:16].replace("T", " ")
                    rel_hl = rel["headline"][:100] + (
                        "…" if len(rel["headline"]) > 100 else "")
                    rel_rows.append(
                        f'<div class="rel-item">'
                        f'<span class="rel-ts">{rel_ts}</span> · '
                        f'{_stage_tag(rel.get("stage",""))} · {rel_hl}'
                        f'</div>'
                    )
                st.markdown(
                    f'<div class="kicker">RELATED ANALYSES</div>'
                    f'{"".join(rel_rows)}',
                    unsafe_allow_html=True,
                )

            # ── Review ──
            st.markdown(
                '<div style="margin-top:14px;padding-top:12px;'
                'border-top:1px solid #e2e8f0">'
                '<div class="kicker">YOUR REVIEW</div></div>',
                unsafe_allow_html=True,
            )
            _RATINGS = ["", "good", "mixed", "poor"]
            current_rating = e.get("rating") or ""
            current_notes  = e.get("notes") or ""
            rc1, rc2 = st.columns([1, 3])
            with rc1:
                new_rating = st.selectbox(
                    "Rating", _RATINGS,
                    index=(_RATINGS.index(current_rating)
                           if current_rating in _RATINGS else 0),
                    key=f"rating_{eid}",
                )
            with rc2:
                new_notes = st.text_input(
                    "Note", value=current_notes, key=f"notes_{eid}",
                    placeholder="Your observations…",
                )
            if new_rating != current_rating or new_notes != current_notes:
                try:
                    update_review(eid, new_rating, new_notes)
                    st.caption("✓ Saved")
                except Exception as ex:
                    st.error(f"Could not save review: {ex}")
