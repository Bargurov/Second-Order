#!/usr/bin/env python3
"""
Telegram bot for Second Order.

Accepts a headline (plain text or forwarded message), calls the local
FastAPI /analyze endpoint, and replies with a compact analysis summary.

Requires:
  TELEGRAM_BOT_TOKEN in .env
  FastAPI backend running on SECOND_ORDER_API_URL (default http://127.0.0.1:8000)

Usage:
  python telegram_bot.py
"""

import os
import sys
import logging
import urllib.request
import urllib.error
import json

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("second_order_bot")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
API_URL = os.getenv("SECOND_ORDER_API_URL", "http://127.0.0.1:8000")

# Daily morning brief schedule
DAILY_BRIEF_ENABLED = os.getenv("DAILY_BRIEF_ENABLED", "").lower() in ("1", "true", "yes")
DAILY_BRIEF_CHAT_ID = os.getenv("DAILY_BRIEF_CHAT_ID", "")
DAILY_BRIEF_TIME = os.getenv("DAILY_BRIEF_TIME", "08:00")  # HH:MM local time

# Watchlist alerts
WATCHLIST_ENABLED = os.getenv("WATCHLIST_ENABLED", "").lower() in ("1", "true", "yes")
WATCHLIST_CHAT_ID = os.getenv("WATCHLIST_CHAT_ID", "")
WATCHLIST_INTERVAL_MIN = int(os.getenv("WATCHLIST_INTERVAL_MIN", "30"))
WATCHLIST_THRESHOLD_PCT = float(os.getenv("WATCHLIST_THRESHOLD_PCT", "3.0"))


# ---------------------------------------------------------------------------
# API client — lightweight, no dependency on the api.py module
# ---------------------------------------------------------------------------

def _api_get(path: str) -> dict:
    """GET a JSON endpoint from the local API."""
    req = urllib.request.Request(f"{API_URL}{path}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _api_post(path: str, body: dict) -> dict:
    """POST JSON to the local API and return the response."""
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{API_URL}{path}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_analyze(headline: str) -> dict:
    """Call the local /analyze endpoint and return the JSON response."""
    return _api_post("/analyze", {"headline": headline})


def call_news() -> dict:
    """Call the local /news endpoint and return the JSON response."""
    return _api_get("/news")


# ---------------------------------------------------------------------------
# Response formatting
# ---------------------------------------------------------------------------

def format_analysis(result: dict) -> str:
    """Format an /analyze response into a compact Telegram message."""
    lines: list[str] = []

    # Header
    headline = result.get("headline", "?")
    lines.append(f"<b>{_esc(headline)}</b>")
    lines.append("")

    # Classification
    stage = result.get("stage", "?")
    persistence = result.get("persistence", "?")
    confidence = result.get("analysis", {}).get("confidence", "?")
    mock = result.get("is_mock", False)

    tags = f"<code>{stage}</code> · <code>{persistence}</code>"
    if mock:
        tags += " · <i>mock</i>"
    else:
        tags += f" · confidence: <code>{confidence}</code>"
    lines.append(tags)
    lines.append("")

    analysis = result.get("analysis", {})

    # What changed
    what = analysis.get("what_changed", "")
    if what and not what.startswith("[mock:"):
        lines.append(f"<b>What changed:</b> {_esc(what)}")
        lines.append("")

    # Mechanism
    mech = analysis.get("mechanism_summary", "")
    if mech and not mech.startswith("[mock:"):
        # Truncate to ~300 chars for Telegram readability
        if len(mech) > 300:
            mech = mech[:297] + "..."
        lines.append(f"<b>Mechanism:</b> {_esc(mech)}")
        lines.append("")

    # Beneficiaries / Losers
    bens = analysis.get("beneficiaries", [])
    losers = analysis.get("losers", [])
    if bens:
        lines.append(f"<b>Beneficiaries:</b> {_esc(', '.join(bens))}")
    if losers:
        lines.append(f"<b>Losers:</b> {_esc(', '.join(losers))}")

    # Key tickers
    ben_tickers = analysis.get("beneficiary_tickers", [])
    los_tickers = analysis.get("loser_tickers", [])
    all_tickers = ben_tickers + los_tickers
    if all_tickers:
        lines.append(f"<b>Tickers:</b> <code>{' '.join(all_tickers)}</code>")

    # Event date
    event_date = result.get("event_date")
    if event_date:
        lines.append(f"<b>Anchored:</b> <code>{event_date}</code>")

    return "\n".join(lines)


def _esc(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_brief(clusters: list[dict], max_items: int = 5) -> str:
    """Format the top N clusters into a compact briefing message.

    Each item shows the headline, a one-line summary, sector/action tags,
    and source count. Skips malformed clusters and notes how many were skipped.
    """
    lines: list[str] = []
    lines.append("<b>Briefing</b>")
    lines.append("")

    rendered = 0
    skipped = 0
    for c in clusters[:max_items + 3]:  # take a few extra in case some skip
        if rendered >= max_items:
            break
        headline = c.get("headline", "")
        if not headline:
            skipped += 1
            continue

        rendered += 1
        # Number + headline
        lines.append(f"<b>{rendered}.</b> {_esc(headline)}")

        # Summary — the cluster-level fused summary
        summary = c.get("summary", "")
        if summary:
            if len(summary) > 200:
                summary = summary[:197] + "..."
            lines.append(f"   {_esc(summary)}")

        # Tags: sector, action, source count
        tags: list[str] = []
        consensus = c.get("consensus") or {}
        sector = consensus.get("sector")
        action = consensus.get("action")
        if sector and sector != "unknown":
            tags.append(sector)
        if action and action != "unknown":
            tags.append(action)
        src_count = c.get("source_count", 0)
        if src_count > 1:
            tags.append(f"{src_count} sources")
        if tags:
            lines.append(f"   <i>{_esc(' · '.join(tags))}</i>")

        lines.append("")

    if rendered == 0:
        return "No headlines available. Try refreshing the inbox."

    if skipped > 0:
        lines.append(f"<i>({skipped} item{'s' if skipped != 1 else ''} skipped)</i>")

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Schedule helpers
# ---------------------------------------------------------------------------

import datetime as _dt


def parse_time(s: str) -> _dt.time | None:
    """Parse HH:MM string into a datetime.time. Returns None on failure."""
    s = s.strip()
    try:
        parts = s.split(":")
        if len(parts) != 2:
            return None
        h, m = int(parts[0]), int(parts[1])
        return _dt.time(hour=h, minute=m)
    except (ValueError, TypeError):
        return None


def build_morning_brief() -> str | None:
    """Fetch news and format a morning brief. Returns message text or None."""
    try:
        data = call_news()
        clusters = data.get("clusters", [])
        if not clusters:
            return None
        return format_brief(clusters, max_items=5)
    except Exception as e:
        logger.error(f"[morning_brief] Failed to build brief: {e}")
        return None


async def _send_morning_brief(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: send the daily brief to the configured chat."""
    chat_id = DAILY_BRIEF_CHAT_ID
    if not chat_id:
        logger.warning("[morning_brief] DAILY_BRIEF_CHAT_ID not set, skipping")
        return

    msg = build_morning_brief()
    if msg is None:
        logger.info("[morning_brief] No headlines available, skipping send")
        return

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=msg,
            parse_mode="HTML",
        )
        logger.info(f"[morning_brief] Sent to chat {chat_id}")
    except Exception as e:
        logger.error(f"[morning_brief] Send failed: {e}")


# ---------------------------------------------------------------------------
# Watchlist alerts
# ---------------------------------------------------------------------------

# Dedupe set: tracks (event_id, symbol, direction) tuples already alerted.
# Lives in memory for the bot session; clears on restart.
_alerted: set[tuple[int, str, str]] = set()


def check_watchlist_alerts(threshold: float = WATCHLIST_THRESHOLD_PCT) -> list[dict]:
    """Poll saved events, run backtest, and return alerts for significant moves.

    Each alert: {event_id, headline, symbol, role, return_5d, direction}.
    Only returns moves that cross the threshold AND haven't been alerted yet.
    """
    alerts: list[dict] = []
    try:
        events = _api_get("/events?limit=25")
    except Exception as e:
        logger.error(f"[watchlist] Failed to load events: {e}")
        return []

    # Filter to testable events
    testable = [
        e for e in events
        if e.get("event_date") and e.get("market_tickers")
    ]
    if not testable:
        return []

    ids = [e["id"] for e in testable]
    try:
        batch = _api_post("/backtest/batch", {"event_ids": ids})
    except Exception as e:
        logger.error(f"[watchlist] Backtest batch failed: {e}")
        return []

    # Build headline lookup
    headline_map = {e["id"]: e.get("headline", "?") for e in testable}

    for result in batch:
        eid = result.get("event_id")
        headline = headline_map.get(eid, "?")
        for outcome in result.get("outcomes", []):
            symbol = outcome.get("symbol", "")
            r5 = outcome.get("return_5d")
            direction = outcome.get("direction") or ""
            if r5 is None or abs(r5) < threshold:
                continue
            key = (eid, symbol, direction)
            if key in _alerted:
                continue
            _alerted.add(key)
            alerts.append({
                "event_id": eid,
                "headline": headline,
                "symbol": symbol,
                "role": outcome.get("role", "?"),
                "return_5d": r5,
                "direction": direction,
            })

    return alerts


def format_alert(alert: dict) -> str:
    """Format a single watchlist alert into a compact Telegram message."""
    sym = alert["symbol"]
    r5 = alert["return_5d"]
    role = alert["role"]
    direction = alert.get("direction", "")
    headline = alert.get("headline", "?")

    sign = "+" if r5 >= 0 else ""
    move_class = "up" if r5 > 0 else "down"

    lines: list[str] = []
    lines.append(f"<b>Alert: {_esc(sym)} {move_class} {sign}{r5:.2f}% (5d)</b>")
    lines.append("")
    lines.append(f"Role: <code>{role}</code>")
    if direction:
        lines.append(f"Signal: <code>{_esc(direction)}</code>")
    lines.append(f"Event: {_esc(headline)}")
    return "\n".join(lines)


async def _poll_watchlist(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: check tickers and send alerts for significant moves."""
    chat_id = WATCHLIST_CHAT_ID
    if not chat_id:
        return

    alerts = check_watchlist_alerts()
    if not alerts:
        return

    for alert in alerts:
        try:
            msg = format_alert(alert)
            await context.bot.send_message(
                chat_id=chat_id,
                text=msg,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"[watchlist] Send failed for {alert.get('symbol')}: {e}")

    logger.info(f"[watchlist] Sent {len(alerts)} alert(s) to chat {chat_id}")


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

import re as _re

# Patterns stripped from the start of a message before analysis.
_NOISE_PREFIX_RE = _re.compile(
    r"^(?:"
    r"(?:hey |yo |omg |wow |look at this|check this|fyi|btw|lol|haha)"
    r"[!.:,\s]*"
    r")+",
    _re.IGNORECASE,
)

# Personal-opinion lead-ins that appear before or after a URL.
_OPINION_RE = _re.compile(
    r"^(?:this (?:feels|looks|seems|is|could be)|i think|my take|imo|imho|"
    r"pretty (?:big|huge|important)|thoughts\??|what do you think)\b",
    _re.IGNORECASE,
)

# Broad emoji range
_EMOJI_CHARS = r"\U0001F300-\U0001FAFF\u2600-\u27BF\u2300-\u23FF\uFE0F"
_TRAILING_EMOJI_RE = _re.compile(
    rf"\n\s*[{_EMOJI_CHARS}\s]+$"
)

_URL_RE = _re.compile(r"https?://\S+")


def _is_headline_like(s: str) -> bool:
    """Heuristic: does this look like an article headline rather than chat opinion?

    Headlines tend to: start with a capital letter or number, contain a named
    entity (country, org), use past/present tense news verbs, and NOT start
    with first-person or opinion markers.
    """
    s = s.strip()
    if not s or len(s) < 10:
        return False
    if _OPINION_RE.match(s):
        return False
    # Headlines typically start with uppercase or a digit
    if s[0].isupper() or s[0].isdigit():
        return True
    return False


def _best_segment(segments: list[str]) -> str:
    """Pick the most headline-like segment from around a URL."""
    # Prefer headline-like segments; among those, prefer longer ones
    candidates = [(s, _is_headline_like(s), len(s)) for s in segments if s]
    headline_like = [s for s, hl, _ in candidates if hl]
    if headline_like:
        return max(headline_like, key=len)
    # No headline-like segment — return the longest non-trivial one
    non_trivial = [s for s, _, ln in candidates if ln >= 10]
    if non_trivial:
        return max(non_trivial, key=len)
    # Fall back to whatever we have
    all_text = [s for s, _, _ in candidates]
    return max(all_text, key=len) if all_text else ""


def extract_headline(
    text: str | None = None,
    caption: str | None = None,
    forward_text: str | None = None,
) -> str | None:
    """Extract the best analysis input from a Telegram message.

    Priority:
    1. forward_text (forwarded article headline/body)
    2. caption (photo/document caption)
    3. text (plain message)

    When a URL is present, splits the text around the URL and picks the
    segment that looks most like an article headline (capitalized, no
    first-person opinion markers). The URL itself is kept as a fallback
    if no text accompanies it.
    """
    raw = forward_text or caption or text or ""
    raw = raw.strip()
    if not raw:
        return None

    # Strip leading chat noise
    cleaned = _NOISE_PREFIX_RE.sub("", raw).strip()

    # Strip trailing emoji lines
    cleaned = _TRAILING_EMOJI_RE.sub("", cleaned).strip()

    urls = _URL_RE.findall(cleaned)

    if urls:
        # Split around the URL(s) to get text segments
        parts = _URL_RE.split(cleaned)
        segments = [p.strip(" \t\n-—·:,") for p in parts if p.strip()]
        result = _best_segment(segments)
        if not result or len(result) < 5:
            result = urls[0]  # bare URL fallback
    else:
        result = cleaned

    # Final cleanup
    result = result.strip(" \t\n-—·:,")

    if not result or len(result) < 5:
        return None

    return result[:500]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    await update.message.reply_text(
        "Second Order analysis bot.\n\n"
        "Send me a headline (or forward a message) and I'll run the analysis pipeline.\n\n"
        "Example: <i>US imposes new tariffs on steel</i>",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    await update.message.reply_text(
        "<b>Usage</b>\n"
        "Send any text headline and I'll analyze it.\n\n"
        "<b>What you get</b>\n"
        "Stage, persistence, mechanism summary, beneficiaries, losers, key tickers, confidence.\n\n"
        "<b>Commands</b>\n"
        "/start — intro\n"
        "/brief — top 5 headlines from the live inbox\n"
        "/help — this message",
        parse_mode="HTML",
    )


async def cmd_brief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /brief — return top clustered headlines from the inbox."""
    await update.message.chat.send_action("typing")

    try:
        data = call_news()
        clusters = data.get("clusters", [])
        if not clusters:
            await update.message.reply_text("No headlines in the inbox right now.")
            return
        reply = format_brief(clusters)
        await update.message.reply_text(reply, parse_mode="HTML")
    except urllib.error.URLError as e:
        logger.error(f"API connection failed: {e}")
        await update.message.reply_text(
            "Could not reach the backend. Is uvicorn running?"
        )
    except Exception as e:
        logger.error(f"Brief failed: {e}")
        await update.message.reply_text(f"Brief failed: {type(e).__name__}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle any text message — extract a headline and analyze it."""
    msg = update.message
    headline = extract_headline(
        text=msg.text,
        caption=msg.caption,
        forward_text=(msg.forward_origin and msg.text) if hasattr(msg, "forward_origin") else None,
    )

    if not headline:
        await msg.reply_text(
            "I couldn't find a headline to analyze. "
            "Send me a news headline, forward a message, or paste an article title."
        )
        return

    await msg.chat.send_action("typing")

    try:
        result = call_analyze(headline)
        reply = format_analysis(result)
        await update.message.reply_text(reply, parse_mode="HTML")
    except urllib.error.URLError as e:
        logger.error(f"API connection failed: {e}")
        await update.message.reply_text(
            "Could not reach the analysis backend. Is uvicorn running?"
        )
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        await update.message.reply_text(
            f"Analysis failed: {type(e).__name__}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set in .env")
        print("Get a token from @BotFather on Telegram and add it to your .env file.")
        sys.exit(1)

    logger.info(f"Starting bot, API URL: {API_URL}")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("brief", cmd_brief))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Schedule daily morning brief
    if DAILY_BRIEF_ENABLED:
        t = parse_time(DAILY_BRIEF_TIME)
        if t and DAILY_BRIEF_CHAT_ID:
            app.job_queue.run_daily(
                _send_morning_brief,
                time=t,
                name="morning_brief",
            )
            logger.info(f"Morning brief scheduled at {t.strftime('%H:%M')} → chat {DAILY_BRIEF_CHAT_ID}")
        else:
            if not DAILY_BRIEF_CHAT_ID:
                logger.warning("DAILY_BRIEF_ENABLED but DAILY_BRIEF_CHAT_ID not set")
            if not t:
                logger.warning(f"DAILY_BRIEF_ENABLED but DAILY_BRIEF_TIME is invalid: {DAILY_BRIEF_TIME!r}")

    # Schedule watchlist alerts
    if WATCHLIST_ENABLED:
        if WATCHLIST_CHAT_ID:
            app.job_queue.run_repeating(
                _poll_watchlist,
                interval=WATCHLIST_INTERVAL_MIN * 60,
                first=60,  # first check 60s after startup
                name="watchlist_poll",
            )
            logger.info(
                f"Watchlist alerts: every {WATCHLIST_INTERVAL_MIN}min, "
                f"threshold {WATCHLIST_THRESHOLD_PCT}%, chat {WATCHLIST_CHAT_ID}"
            )
        else:
            logger.warning("WATCHLIST_ENABLED but WATCHLIST_CHAT_ID not set")

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
