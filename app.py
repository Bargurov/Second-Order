# app.py
# Streamlit UI for Geo Mechanism Project V1.5.
# Run with: streamlit run app.py

import streamlit as st
from datetime import datetime

from classify import classify_stage, classify_persistence
from analyze_event import analyze_event
from market_check import market_check as run_market_check
from db import init_db, save_event, load_recent_events
from news_sources import fetch_all, cluster_headlines, source_tier

# ---------------------------------------------------------------------------
# CSS — small overrides that Streamlit doesn't expose natively
# ---------------------------------------------------------------------------

_CUSTOM_CSS = """
<style>
/* Tighter metric cards */
div[data-testid="stMetric"] {
    background: #f8f9fa;
    border: 1px solid #e9ecef;
    border-radius: 8px;
    padding: 12px 16px 8px 16px;
}
div[data-testid="stMetric"] label { font-size: 0.78rem; color: #6c757d; }
div[data-testid="stMetric"] div[data-testid="stMetricValue"] { font-size: 1.15rem; }

/* Badge helpers injected via markdown */
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.82rem;
    font-weight: 600;
    letter-spacing: 0.02em;
}
.badge-blue   { background: #dbeafe; color: #1e40af; }
.badge-purple { background: #ede9fe; color: #5b21b6; }
.badge-green  { background: #dcfce7; color: #166534; }
.badge-yellow { background: #fef9c3; color: #854d0e; }
.badge-red    { background: #fee2e2; color: #991b1b; }
.badge-gray   { background: #f3f4f6; color: #374151; }

/* Card-like containers */
.card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    padding: 20px 24px;
    margin-bottom: 12px;
}

/* Source tier pills */
.tier-high   { background: #dcfce7; color: #166534; }
.tier-medium { background: #fef9c3; color: #854d0e; }
.tier-low    { background: #f3f4f6; color: #6b7280; }
.source-pill {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 10px;
    font-size: 0.73rem;
    margin-right: 4px;
}
.agreement-mixed {
    display: inline-block;
    font-size: 0.73rem;
    color: #b45309;
    margin-left: 4px;
}

/* Subtle section headers */
.section-label {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #9ca3af;
    margin-bottom: 2px;
}
</style>
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stage_badge(stage: str) -> str:
    colors = {
        "anticipation": "blue", "realized": "green", "escalation": "red",
        "de-escalation": "purple", "normalization": "gray",
    }
    c = colors.get(stage, "gray")
    return f'<span class="badge badge-{c}">{stage}</span>'

def _persistence_badge(persistence: str) -> str:
    colors = {"transient": "gray", "medium": "yellow", "structural": "purple"}
    c = colors.get(persistence, "gray")
    return f'<span class="badge badge-{c}">{persistence}</span>'

def _confidence_badge(confidence: str) -> str:
    colors = {"low": "red", "medium": "yellow", "high": "green"}
    c = colors.get(confidence, "gray")
    return f'<span class="badge badge-{c}">{confidence}</span>'

def _direction_icon(tag: str | None) -> str:
    if not tag:
        return "—"
    if tag.startswith("supports"):
        return f"✅ {tag}"
    return f"⚠️ {tag}"

def _source_pills(sources: list[dict]) -> str:
    """Render source names as tier-coloured pills."""
    parts = []
    for s in sources:
        tier = s["tier"]
        parts.append(f'<span class="source-pill tier-{tier}">{s["name"]}</span>')
    return "".join(parts)


def _build_event_context(cluster: dict) -> str:
    """Build a multi-source context string for the LLM from a cluster.

    Always includes structured consensus fields when available.
    For multi-source clusters, also includes source corroboration details.
    """
    con = cluster.get("consensus", {})
    lines: list[str] = []

    # Structured consensus block — always included when populated
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

    # Multi-source details — only for clusters with >1 source
    if cluster["source_count"] > 1:
        lines.append("")
        lines.append("Multi-source context:")
        lines.append(f"  Summary: {cluster['summary']}")

        source_parts = []
        for s in cluster["sources"]:
            source_parts.append(f"{s['name']} ({s['tier']} tier)")
        lines.append(f"  Sources ({cluster['source_count']}): {', '.join(source_parts)}")
        lines.append(f"  Source agreement: {cluster['agreement']}")

        if cluster["agreement"] == "mixed":
            lines.append(
                "  Note: sources frame this event differently. "
                "Weigh the higher-tier account more heavily, but acknowledge "
                "the disagreement in your analysis if it affects the mechanism."
            )

    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _render_result(analysis: dict, market: dict, stage: str,
                   persistence: str, event_date: str | None) -> None:
    """Render the full analysis result card (called inline under a headline)."""

    confidence = analysis["confidence"]
    badges_html = (
        f'<div style="margin-bottom:16px">'
        f'<span class="section-label">CLASSIFICATION</span><br>'
        f'{_stage_badge(stage)} &nbsp; {_persistence_badge(persistence)} &nbsp; '
        f'{_confidence_badge(confidence)}'
        f'</div>'
    )
    st.markdown(badges_html, unsafe_allow_html=True)

    if analysis.get("validation_warnings"):
        st.warning("  ·  ".join(analysis["validation_warnings"]))

    # -- What changed --
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<span class="section-label">WHAT CHANGED</span>', unsafe_allow_html=True)
    st.markdown(analysis["what_changed"])
    st.markdown('</div>', unsafe_allow_html=True)

    # -- Mechanism --
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<span class="section-label">MECHANISM</span>', unsafe_allow_html=True)
    st.markdown(analysis["mechanism_summary"])
    st.markdown('</div>', unsafe_allow_html=True)

    # -- Beneficiaries / Losers --
    col_b, col_l = st.columns(2)

    with col_b:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<span class="section-label">BENEFICIARIES</span>', unsafe_allow_html=True)
        for b in analysis["beneficiaries"]:
            st.markdown(f"- {b}")
        tickers_up = analysis["beneficiary_tickers"]
        if tickers_up:
            st.success("Watch ↑ :  " + "  ·  ".join(tickers_up))
        else:
            st.caption("No tickers identified")
        st.markdown('</div>', unsafe_allow_html=True)

    with col_l:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<span class="section-label">LOSERS</span>', unsafe_allow_html=True)
        for lo in analysis["losers"]:
            st.markdown(f"- {lo}")
        tickers_down = analysis["loser_tickers"]
        if tickers_down:
            st.error("Watch ↓ :  " + "  ·  ".join(tickers_down))
        else:
            st.caption("No tickers identified")
        st.markdown('</div>', unsafe_allow_html=True)

    # -- Market check table --
    st.markdown("##### 📈 Market Check")
    if event_date:
        st.caption(f"Returns anchored to event date: {event_date}")
    else:
        st.caption("Current prices — rolling 3-month window, not event-date validation.")

    tickers = market["tickers"]
    if tickers:
        hdr = st.columns([1.2, 1, 1, 1.2, 2])
        for col, label in zip(hdr, ["Symbol", "Role", "5d", "Label", "Direction"]):
            col.markdown(f"<span class='section-label'>{label.upper()}</span>", unsafe_allow_html=True)
        for t in tickers:
            r5 = f"{t['return_5d']:+.1f}%" if t.get("return_5d") is not None else "n/a"
            row = st.columns([1.2, 1, 1, 1.2, 2])
            row[0].markdown(f"**{t['symbol']}**")
            row[1].caption(t["role"])
            row[2].markdown(r5)
            row[3].caption(t.get("label", "—"))
            row[4].markdown(_direction_icon(t.get("direction_tag")))
    else:
        st.caption("No tickers to check.")

    note_lines = market["note"].splitlines()
    summary = next((ln.strip() for ln in reversed(note_lines) if "Hypothesis support" in ln), None)
    if summary:
        st.info(summary)


def _run_analysis(headline: str, event_date_input,
                   event_context: str = "") -> dict:
    """Run the full pipeline and return a result dict for caching."""
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

    return {
        "stage": stage, "persistence": persistence,
        "analysis": analysis, "market": market,
        "event_date": event_date,
    }


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

init_db()

st.set_page_config(page_title="Geo Mechanism", page_icon="🌍", layout="centered")
st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)

st.markdown("## 🌍 Geo Mechanism Project")
st.markdown(
    "Identify hidden economic mechanisms behind geopolitical events — "
    "classify, hypothesize, and validate against market data.",
)

# Session state: which inbox item is active, and its cached result
if "active_idx" not in st.session_state:
    st.session_state.active_idx = None      # index of expanded cluster, or None
if "active_result" not in st.session_state:
    st.session_state.active_result = None   # cached pipeline output dict

# ---------------------------------------------------------------------------
# News Inbox
# ---------------------------------------------------------------------------

st.markdown("---")
st.markdown("#### 📰 News Inbox")

col_date, col_spacer = st.columns([1, 2])
with col_date:
    event_date_input = st.date_input(
        "Event date (optional)",
        value=None,
        help="Anchor market returns to this date instead of the rolling window.",
    )

@st.cache_data(ttl=600, show_spinner="Fetching headlines…")
def _cached_fetch():
    records = fetch_all()
    return cluster_headlines(records)

inbox_clusters = _cached_fetch()

if not inbox_clusters:
    st.caption("No headlines available. Add entries to `news_inbox.json` or check RSS connectivity.")
else:
    for idx, cluster in enumerate(inbox_clusters[:15]):
        pub = cluster["published_at"][:16].replace("T", " ") if cluster["published_at"] else ""
        is_active = (st.session_state.active_idx == idx)

        # -- Headline row --
        col_text, col_btn = st.columns([6, 1])
        with col_text:
            st.markdown(cluster["headline"])
            pills = _source_pills(cluster["sources"])
            mixed = (
                '<span class="agreement-mixed">⚠ sources differ</span>'
                if cluster["agreement"] == "mixed" else ""
            )
            meta = f'{pills} {mixed}'
            if pub:
                meta += f'&nbsp; · &nbsp;<span style="font-size:0.73rem;color:#9ca3af">{pub}</span>'
            st.markdown(meta, unsafe_allow_html=True)

            # Merged summary — only show when cluster has >1 source
            if cluster["source_count"] > 1:
                st.caption(cluster["summary"])
        with col_btn:
            btn_label = "Close" if is_active else "Analyze"
            if st.button(btn_label, key=f"inbox_{idx}", use_container_width=True):
                if is_active:
                    # Toggle off — close the open result
                    st.session_state.active_idx = None
                    st.session_state.active_result = None
                else:
                    # Open this headline — clear cached result so pipeline runs
                    st.session_state.active_idx = idx
                    st.session_state.active_result = None
                st.rerun()

        # -- Inline result card (only for the active headline) --
        if is_active:
            headline = cluster["headline"].strip()
            if len(headline) > 500:
                headline = headline[:500]

            # Run the pipeline once and cache in session state
            if st.session_state.active_result is None:
                ctx = _build_event_context(cluster)
                with st.spinner("Classifying and analyzing…"):
                    st.session_state.active_result = _run_analysis(
                        headline, event_date_input, event_context=ctx,
                    )

            res = st.session_state.active_result
            _render_result(
                res["analysis"], res["market"],
                res["stage"], res["persistence"], res["event_date"],
            )
            st.markdown("---")

# ---------------------------------------------------------------------------
# Recent Events
# ---------------------------------------------------------------------------

st.markdown("---")
st.markdown("#### 🕓 Recent Events")

events = load_recent_events(10)

if not events:
    st.caption("No events saved yet. Run an analysis above to get started.")
else:
    for e in events:
        truncated = e["headline"][:100] + ("…" if len(e["headline"]) > 100 else "")
        with st.expander(truncated, expanded=False):
            badges = (
                f'{_stage_badge(e["stage"])} &nbsp; '
                f'{_persistence_badge(e["persistence"])} &nbsp; '
                f'{_confidence_badge(e["confidence"])}'
            )
            st.markdown(badges, unsafe_allow_html=True)
            st.caption(e.get("timestamp", ""))

            mech = e.get("mechanism_summary") or "—"
            st.markdown(f"**Mechanism:** {mech}")

            saved_tickers = e.get("market_tickers", [])
            if saved_tickers:
                b_t = [t for t in saved_tickers if t["role"] == "beneficiary"]
                l_t = [t for t in saved_tickers if t["role"] == "loser"]
                tc1, tc2 = st.columns(2)
                with tc1:
                    if b_t:
                        st.markdown('<span class="section-label">WATCH ↑</span>', unsafe_allow_html=True)
                        for t in b_t:
                            r5 = f"{t['return_5d']:+.1f}%" if t.get("return_5d") is not None else "n/a"
                            st.markdown(f"**{t['symbol']}** · 5d: {r5} · {_direction_icon(t.get('direction_tag'))}")
                with tc2:
                    if l_t:
                        st.markdown('<span class="section-label">WATCH ↓</span>', unsafe_allow_html=True)
                        for t in l_t:
                            r5 = f"{t['return_5d']:+.1f}%" if t.get("return_5d") is not None else "n/a"
                            st.markdown(f"**{t['symbol']}** · 5d: {r5} · {_direction_icon(t.get('direction_tag'))}")

            if e.get("notes"):
                st.caption(f"📝 {e['notes']}")
