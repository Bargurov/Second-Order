"""G2 point-in-time state-data acquisition substrate (Mission G, g0-v1).

Implements the acquisition/readiness layer for the five frozen G0 state
dimensions across the G1 candidate ledgers. Point-in-time discipline:

* conservative cutoff = last completed trading session STRICTLY before the
  source-pinned event date (reference calendar: the VIX session calendar);
* same-day availability class (index/ETF closes, FOMC decisions published
  2 p.m. ET): an observation dated at the cutoff is eligible;
* next-day availability class (Treasury constant-maturity curve, credit
  index levels): an observation dated at the cutoff is treated as published
  AFTER the cutoff close and is NOT eligible - the latest eligible value is
  the prior session's;
* trailing windows never shorten silently: a 252-session percentile or a
  200-session moving average with insufficient eligible history is
  UNAVAILABLE with a reason, never approximated;
* a blocked source is reported blocked, never proxied.

Sources (all zero-cost; no paid request; nothing here touches events.db or
the existing price_cache):

* fed_policy_path  - repo-internal: the G1A FOMC frame's target-range
  timeline plus the official 2016-2017 pre-frame anchor decisions (policy
  decisions are published same-day and never revised);
* vix_level_percentile - Cboe official VIX history CSV (same-day close);
* spy_trend_ma200  - daily SPY closes via the public Yahoo chart endpoint
  (same-day close; RAW closes - the market-convention price index for
  moving-average distance; stated, not silent). The existing price_cache is
  NOT used for this dimension: it is event-window shaped (about 74 percent
  session coverage), so trailing windows over it would silently shrink;
* curve_2s10s      - official Treasury daily yield-curve CSVs ("10 Yr"
  minus "2 Yr", next-day availability class);
* credit_hy_oas    - ICE BofA US High Yield OAS via the authenticated FRED
  API (free registered key resolved from the environment or the gitignored
  .env; the key authenticates the request and is never stored, logged, or
  cached). FRED distributes only a rolling three-year window of this ICE
  series (since April 2026), so cutoffs before the surviving window stay
  source_missing - disclosed, never proxied.

Local cache: ``g_state_cache/`` (gitignored) with per-series retrieval
metadata (source, URL, observation range, retrieval timestamp). No cache or
DB in the repository is mutated; no generated data artifact is committed.

Readiness artifacts are outcome-blind by construction: rows carry only the
whitelisted fields in ``READINESS_FIELDS`` - no market response of any kind.

Usage (read-only unless --fetch):

    python scripts/g_state_acquisition.py --fetch     # bounded acquisition
    python scripts/g_state_acquisition.py --probe     # 97-candidate readiness
    python scripts/g_state_acquisition.py --probe --json
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "g_state_cache"

G1A_PATH = ROOT / "stats" / "G1A_FOMC_FRAME_INVENTORY.md"
G1B_PATH = ROOT / "stats" / "G1B_OPEC_DESIGNED_RESERVOIR.md"

# ---------------------------------------------------------------------------
# Source contracts (documented constants; the readiness report renders these)
# ---------------------------------------------------------------------------

SOURCE_CONTRACTS: dict[str, dict[str, str]] = {
    "fed_policy_path": {
        "source": "repo-internal: G1A FOMC frame target-range timeline + "
                  "official 2016-2017 anchor decisions",
        "series": "FOMC target-range midpoint; net change over a six-month "
                  "calendar lookback",
        "frequency": "event-driven (decision dates)",
        "observation": "decision announcement date",
        "availability": "same_day (statements publish 2 p.m. ET, before the "
                        "session close)",
        "revision": "never revised",
        "range_needed": "2017-07 onward (six months before the earliest "
                        "2018-01 cutoff)",
        "missing_rule": "lookback preceding the timeline start -> "
                        "insufficient_history",
    },
    "vix_level_percentile": {
        "source": "Cboe official VIX history CSV",
        "series": "VIX daily close; level at cutoff + trailing 252-session "
                  "percentile",
        "frequency": "daily (trading sessions)",
        "observation": "session date",
        "availability": "same_day (index close, published at/with the close)",
        "revision": "not revised",
        "range_needed": "2017-01 onward (252 sessions before the earliest "
                        "cutoff)",
        "missing_rule": "fewer than 252 eligible sessions -> "
                        "insufficient_history; absent series -> "
                        "source_missing",
    },
    "spy_trend_ma200": {
        "source": "Yahoo public chart endpoint, SPY daily RAW closes "
                  "(price-index convention for moving-average distance; the "
                  "event-study adjusted-preferred policy governs readouts, "
                  "not this state series - stated, not silent)",
        "series": "SPY close vs 200-session simple moving average, percent "
                  "distance",
        "frequency": "daily (trading sessions)",
        "observation": "session date",
        "availability": "same_day",
        "revision": "not revised",
        "range_needed": "2017-03 onward (200 sessions before the earliest "
                        "cutoff)",
        "missing_rule": "fewer than 200 eligible sessions -> "
                        "insufficient_history; absent series -> "
                        "source_missing",
    },
    "curve_2s10s": {
        "source": "U.S. Treasury daily yield-curve CSVs (official CMT rates)",
        "series": "10 Yr minus 2 Yr constant-maturity spread, level at "
                  "cutoff",
        "frequency": "daily (business days)",
        "observation": "rate date",
        "availability": "next_day (conservative: the daily rate table is "
                        "treated as published after that session's close, so "
                        "the latest eligible value at a cutoff is the PRIOR "
                        "session's)",
        "revision": "effectively unrevised; republication is rare and would "
                    "be visible in retrieval metadata",
        "range_needed": "2017-12 onward",
        "missing_rule": "no eligible observation -> source_missing",
    },
    "credit_hy_oas": {
        "source": "ICE BofA US High Yield OAS via the official FRED API "
                  "(api.stlouisfed.org, free registered key; the key "
                  "authenticates the request only and never enters cache "
                  "metadata or logs)",
        "series": "high-yield OAS level at cutoff",
        "frequency": "daily (business days)",
        "observation": "index date",
        "availability": "next_day (FRED posts the series the next business "
                        "morning - observed via the release last_updated "
                        "stamp; ALFRED realtime_start is back-dated to the "
                        "observation date and is NOT an availability record)",
        "revision": "effectively unrevised (sampled observations are "
                    "single-valued across all surviving vintages)",
        "range_needed": "2017-12 onward; FRED distributes only a rolling "
                        "three-year window of this ICE series (since April "
                        "2026), so history before 2023-07-04 is "
                        "source-withdrawn",
        "missing_rule": "cutoff at/before the surviving window start -> "
                        "source_missing; never proxied",
    },
}

# FOMC target-range midpoints. 2018-2025 entries are derived from the G1A
# frame's per-decision target ranges; the 2016-2017 anchors are the official
# pre-frame decisions needed so a six-month lookback from early-2018 cutoffs
# has a defined starting level. Policy decisions publish same-day (2 p.m. ET)
# and are never revised.
FED_TARGET_TIMELINE: list[tuple[str, float]] = [
    ("2016-12-14", 0.625),
    ("2017-03-15", 0.875),
    ("2017-06-14", 1.125),
    ("2017-12-13", 1.375),
    ("2018-03-21", 1.625),
    ("2018-06-13", 1.875),
    ("2018-09-26", 2.125),
    ("2018-12-19", 2.375),
    ("2019-07-31", 2.125),
    ("2019-09-18", 1.875),
    ("2019-10-30", 1.625),
    ("2020-03-03", 1.125),
    ("2020-03-15", 0.125),
    ("2022-03-16", 0.375),
    ("2022-05-04", 0.875),
    ("2022-06-15", 1.625),
    ("2022-07-27", 2.375),
    ("2022-09-21", 3.125),
    ("2022-11-02", 3.875),
    ("2022-12-14", 4.375),
    ("2023-02-01", 4.625),
    ("2023-03-22", 4.875),
    ("2023-05-03", 5.125),
    ("2023-07-26", 5.375),
    ("2024-09-18", 4.875),
    ("2024-11-07", 4.625),
    ("2024-12-18", 4.375),
    ("2025-09-17", 4.125),
    ("2025-10-29", 3.875),
    ("2025-12-10", 3.625),
]

# Whitelisted readiness-row fields (outcome-blindness firewall).
READINESS_FIELDS = frozenset({
    "candidate_id", "lane", "event_date", "cutoff", "cutoff_resolved",
    "dimensions", "complete_vector", "dimensions_available",
})

DIMENSIONS = ("fed_policy_path", "vix_level_percentile", "spy_trend_ma200",
              "curve_2s10s", "credit_hy_oas")


# ---------------------------------------------------------------------------
# Point-in-time primitives (pure)
# ---------------------------------------------------------------------------


def conservative_cutoff(event_iso: str,
                        sessions: Sequence[str]) -> Optional[str]:
    """Last completed session STRICTLY before the event date, or None."""
    if not sessions:
        return None
    i = bisect.bisect_left(list(sessions), event_iso)
    if i == 0:
        return None
    return sessions[i - 1]


def latest_eligible(series: dict[str, float], cutoff: str,
                    *, availability: str) -> Optional[tuple[str, float]]:
    """Latest observation eligible at the cutoff under the series' class.

    ``same_day``: observation date <= cutoff. ``next_day``: observation date
    strictly < cutoff (a value dated at the cutoff publishes after the
    cutoff close). Returns (obs_date, value) or None.
    """
    if not series:
        return None
    dates = sorted(series)
    if availability == "same_day":
        i = bisect.bisect_right(dates, cutoff)
    elif availability == "next_day":
        i = bisect.bisect_left(dates, cutoff)
    else:  # pragma: no cover - contract misuse
        raise ValueError(f"unknown availability class {availability!r}")
    if i == 0:
        return None
    d = dates[i - 1]
    return d, series[d]


def trailing_percentile(series: dict[str, float], cutoff: str,
                        *, window: int) -> dict[str, Any]:
    """Trailing percentile of the cutoff value over the last ``window``
    eligible observations (same-day class), inclusive rank.

    Never shortens: fewer than ``window`` eligible observations ->
    ``{"value": None, "reason": "insufficient_history"}``. Future
    observations cannot affect the result (only dates <= cutoff are read).
    """
    dates = sorted(d for d in series if d <= cutoff)
    if len(dates) < window:
        return {"value": None, "reason": "insufficient_history"}
    tail = dates[-window:]
    values = [series[d] for d in tail]
    current = values[-1]
    rank = sum(1 for v in values if v <= current)
    return {"value": rank / window, "reason": None}


def ma_distance(series: dict[str, float], cutoff: str,
                *, window: int) -> dict[str, Any]:
    """Percent distance of the cutoff close from its trailing ``window``
    simple moving average (same-day class). Same no-shortening contract."""
    dates = sorted(d for d in series if d <= cutoff)
    if len(dates) < window:
        return {"value": None, "reason": "insufficient_history"}
    tail = [series[d] for d in dates[-window:]]
    ma = sum(tail) / window
    if ma == 0:  # pragma: no cover - degenerate fixture guard
        return {"value": None, "reason": "insufficient_history"}
    return {"value": tail[-1] / ma - 1.0, "reason": None}


def _shift_months(iso: str, months: int) -> str:
    d = date.fromisoformat(iso)
    m = d.month - months
    y = d.year
    while m <= 0:
        m += 12
        y -= 1
    # clamp the day into the target month
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day).isoformat()
        except ValueError:
            continue
    raise AssertionError("unreachable")


def fed_net_change(timeline: Sequence[tuple[str, float]], cutoff: str,
                   *, months: int = 6) -> dict[str, Any]:
    """Net target-range-midpoint change over the calendar lookback ending at
    the cutoff. Decisions are same-day eligible (dated <= cutoff). A lookback
    date preceding the timeline start -> insufficient_history."""
    def level_at(d: str) -> Optional[float]:
        lvl = None
        for dt, mid in timeline:
            if dt <= d:
                lvl = mid
            else:
                break
        return lvl

    now = level_at(cutoff)
    then_date = _shift_months(cutoff, months)
    then = level_at(then_date)
    if now is None or then is None:
        return {"value": None, "reason": "insufficient_history"}
    return {"value": now - then, "reason": None}


# ---------------------------------------------------------------------------
# Candidate readiness (outcome-blind)
# ---------------------------------------------------------------------------


@dataclass
class SourceBundle:
    """The acquired state sources handed to the readiness probe."""
    sessions: Sequence[str]
    vix: Optional[dict[str, float]]
    spy: Optional[dict[str, float]]
    curve_2s10s: Optional[dict[str, float]]
    hy_oas: Optional[dict[str, float]]
    fed_timeline: Sequence[tuple[str, float]]
    blocked: dict[str, str] = field(default_factory=dict)


def _dim_status(available: bool, reason: Optional[str]) -> dict[str, Any]:
    return {"available": available, "reason": reason}


def candidate_readiness(candidate: dict[str, Any],
                        bundle: SourceBundle) -> dict[str, Any]:
    """One whitelisted, outcome-blind readiness row for one candidate."""
    cutoff = conservative_cutoff(candidate["event_date"], bundle.sessions)
    dims: dict[str, dict[str, Any]] = {}

    if cutoff is None:
        for name in DIMENSIONS:
            dims[name] = _dim_status(False, "cutoff_unresolved")
    else:
        # fed policy path
        out = fed_net_change(bundle.fed_timeline, cutoff, months=6)
        dims["fed_policy_path"] = _dim_status(out["value"] is not None,
                                              out["reason"])
        # vix level + percentile
        if bundle.vix is None:
            dims["vix_level_percentile"] = _dim_status(
                False, bundle.blocked.get("vix", "source_missing"))
        else:
            lvl = latest_eligible(bundle.vix, cutoff, availability="same_day")
            pct = trailing_percentile(bundle.vix, cutoff, window=252)
            ok = lvl is not None and pct["value"] is not None
            dims["vix_level_percentile"] = _dim_status(
                ok, None if ok else (pct["reason"] or "source_missing"))
        # spy trend
        if bundle.spy is None:
            dims["spy_trend_ma200"] = _dim_status(
                False, bundle.blocked.get("spy", "source_missing"))
        else:
            out = ma_distance(bundle.spy, cutoff, window=200)
            dims["spy_trend_ma200"] = _dim_status(out["value"] is not None,
                                                  out["reason"])
        # curve level (next-day class)
        if bundle.curve_2s10s is None:
            dims["curve_2s10s"] = _dim_status(
                False, bundle.blocked.get("curve_2s10s", "source_missing"))
        else:
            got = latest_eligible(bundle.curve_2s10s, cutoff,
                                  availability="next_day")
            dims["curve_2s10s"] = _dim_status(
                got is not None, None if got else "source_missing")
        # credit level (next-day class)
        if bundle.hy_oas is None:
            dims["credit_hy_oas"] = _dim_status(
                False, bundle.blocked.get("hy_oas", "source_missing"))
        else:
            got = latest_eligible(bundle.hy_oas, cutoff,
                                  availability="next_day")
            dims["credit_hy_oas"] = _dim_status(
                got is not None, None if got else "source_missing")

    n_ok = sum(1 for d in dims.values() if d["available"])
    return {
        "candidate_id": candidate["candidate_id"],
        "lane": candidate["lane"],
        "event_date": candidate["event_date"],
        "cutoff": cutoff,
        "cutoff_resolved": cutoff is not None,
        "dimensions": dims,
        "complete_vector": n_ok == len(DIMENSIONS),
        "dimensions_available": n_ok,
    }


# ---------------------------------------------------------------------------
# G1 candidate-ledger parsers (deterministic)
# ---------------------------------------------------------------------------

_G1A_ROW = re.compile(r"^\|\s*`fomc-policy-decision-(\d{4}-\d{2}-\d{2})`\s*\|")
_G1B_ROW = re.compile(r"^\|\s*D\d{2}\s*\|")
_BACKTICKED = re.compile(r"`([a-z0-9][a-z0-9-]+)`")


def parse_g1a_candidates(path: str) -> list[dict[str, str]]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = _G1A_ROW.match(line)
        if m:
            d = m.group(1)
            rows.append({"candidate_id": f"fomc-policy-decision-{d}",
                         "event_date": d,
                         "lane": "frame_complete_historical"})
    return rows


def parse_g1b_candidates(path: str) -> list[dict[str, str]]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not _G1B_ROW.match(line):
            continue
        cells = [c.strip() for c in line.split("|")]
        # cells: '', key, date, source ref, title, action, canonical, anchor,
        #        dup/mirror, ''
        if len(cells) < 10:
            continue
        mirror = cells[8].lower()
        if mirror not in ("canonical", "none"):
            continue  # mirrors and held rows never advance
        ident = _BACKTICKED.search(cells[6])
        if not ident:
            continue
        rows.append({"candidate_id": ident.group(1),
                     "event_date": cells[2],
                     "lane": "designed_contrast"})
    return rows


# ---------------------------------------------------------------------------
# Zero-cost acquisition (bounded; writes only the gitignored local cache)
# ---------------------------------------------------------------------------

_UA = {"User-Agent": "Mozilla/5.0"}
FETCH_START = "2016-06-01"   # covers 252 sessions + 6-month lookback margins
FETCH_END = "2025-12-31"


def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _mmddyyyy_to_iso(s: str) -> str:
    m, d, y = s.split("/")
    return f"{y}-{int(m):02d}-{int(d):02d}"


def fetch_vix() -> tuple[dict[str, float], dict[str, Any]]:
    url = ("https://cdn.cboe.com/api/global/us_indices/daily_prices/"
           "VIX_History.csv")
    raw = _get(url).decode("utf-8", "replace")
    series: dict[str, float] = {}
    for line in raw.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 5 or "/" not in parts[0]:
            continue
        iso = _mmddyyyy_to_iso(parts[0])
        if FETCH_START <= iso <= FETCH_END:
            series[iso] = float(parts[4])
    meta = {"series": "VIX close", "source": "Cboe", "url": url}
    return series, meta


def fetch_spy() -> tuple[dict[str, float], dict[str, Any]]:
    p1 = int(datetime(2016, 6, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/SPY"
           f"?period1={p1}&period2={p2}&interval=1d")
    payload = json.loads(_get(url).decode("utf-8"))
    result = payload["chart"]["result"][0]
    stamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    series: dict[str, float] = {}
    for ts, c in zip(stamps, closes):
        if c is None:
            continue
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        if FETCH_START <= iso <= FETCH_END:
            series[iso] = float(c)
    meta = {"series": "SPY raw daily close", "source": "Yahoo chart endpoint",
            "url": url}
    return series, meta


def fetch_curve_2s10s() -> tuple[dict[str, float], dict[str, Any]]:
    series: dict[str, float] = {}
    years = range(2016, 2026)
    base = ("https://home.treasury.gov/resource-center/data-chart-center/"
            "interest-rates/daily-treasury-rates.csv/{y}/all"
            "?type=daily_treasury_yield_curve&field_tdr_date_value={y}"
            "&page&_format=csv")
    for y in years:
        raw = _get(base.format(y=y)).decode("utf-8", "replace")
        lines = raw.splitlines()
        header = [h.strip().strip('"') for h in lines[0].split(",")]
        i2, i10 = header.index("2 Yr"), header.index("10 Yr")
        idate = header.index("Date")
        for line in lines[1:]:
            cells = [c.strip().strip('"') for c in line.split(",")]
            if len(cells) <= max(i2, i10):
                continue
            try:
                iso = _mmddyyyy_to_iso(cells[idate])
                v2, v10 = float(cells[i2]), float(cells[i10])
            except (ValueError, IndexError):
                continue
            if FETCH_START <= iso <= FETCH_END:
                series[iso] = v10 - v2
    meta = {"series": "10 Yr minus 2 Yr CMT spread",
            "source": "U.S. Treasury daily yield-curve CSVs",
            "url": base.format(y="<year>")}
    return series, meta


_HY_OAS_SERIES_ID = "BAMLH0A0HYM2"


def _fred_api_key(env: Mapping[str, str],
                  dotenv_path: Path) -> Optional[str]:
    """Resolve the FRED API key: environment first, then the gitignored
    .env file. Returns None when absent. The value is never printed."""
    key = (env.get("FRED_API_KEY") or "").strip()
    if key:
        return key
    if dotenv_path.exists():
        for line in dotenv_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("FRED_API_KEY="):
                key = line.split("=", 1)[1].strip()
                return key or None
    return None


def _hy_oas_request_url(api_key: str) -> str:
    qs = urllib.parse.urlencode({
        "series_id": _HY_OAS_SERIES_ID,
        "observation_start": FETCH_START,
        "observation_end": FETCH_END,
        "file_type": "json",
        "api_key": api_key,
    })
    return f"https://api.stlouisfed.org/fred/series/observations?{qs}"


def _redact_api_key(url: str) -> str:
    return re.sub(r"api_key=[^&]*", "api_key=REDACTED", url)


def _parse_fred_observations(payload: dict[str, Any]) -> dict[str, float]:
    """FRED observations JSON -> {iso_date: float}, dropping the "."
    missing-value markers and anything outside the substrate window."""
    series: dict[str, float] = {}
    for row in payload.get("observations", []):
        d, v = row.get("date", ""), row.get("value", ".")
        if v == "." or not (FETCH_START <= d <= FETCH_END):
            continue
        series[d] = float(v)
    return series


def fetch_hy_oas(api_key: Optional[str], *,
                 getter: Callable[..., bytes] = _get,
                 ) -> tuple[dict[str, float], dict[str, Any]]:
    """Authenticated FRED acquisition of the ICE BofA US HY OAS level.

    The key authenticates the request only; the cached metadata records a
    REDACTED url. Without a key this raises before any network call - the
    dimension stays blocked rather than proxied or fetched anonymously.
    """
    if not api_key:
        raise ValueError("FRED_API_KEY required for credit_hy_oas")
    url = _hy_oas_request_url(api_key)
    payload = json.loads(getter(url).decode("utf-8"))
    series = _parse_fred_observations(payload)
    meta = {
        "series": f"ICE BofA US High Yield OAS ({_HY_OAS_SERIES_ID})",
        "source": "official FRED API (authenticated, free registered key)",
        "url": _redact_api_key(url),
    }
    return series, meta


def probe_hy_oas_blocked() -> dict[str, Any]:
    """Bounded evidence probe for the blocked credit dimension (no proxy)."""
    url = ("https://fred.stlouisfed.org/graph/fredgraph.csv"
           "?id=BAMLH0A0HYM2&cosd=2020-01-01&coed=2020-01-15")
    try:
        _get(url, timeout=8)
        return {"blocked": False, "evidence": "reachable"}
    except Exception as exc:  # noqa: BLE001 - evidence capture
        return {"blocked": True,
                "evidence": f"{type(exc).__name__}: {exc}", "url": url}


def _save(name: str, series: dict[str, float], meta: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    dates = sorted(series)
    payload = {
        "meta": {
            **meta,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "observations": len(series),
            "first": dates[0] if dates else None,
            "last": dates[-1] if dates else None,
        },
        "data": series,
    }
    (CACHE_DIR / f"{name}.json").write_text(
        json.dumps(payload, sort_keys=True), encoding="utf-8")


def _load(name: str) -> Optional[dict[str, float]]:
    p = CACHE_DIR / f"{name}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))["data"]


def run_fetch() -> None:
    vix, m = fetch_vix()
    _save("vix", vix, m)
    print(f"vix: {len(vix)} obs")
    spy, m = fetch_spy()
    _save("spy", spy, m)
    print(f"spy: {len(spy)} obs")
    curve, m = fetch_curve_2s10s()
    _save("curve_2s10s", curve, m)
    print(f"curve_2s10s: {len(curve)} obs")
    key = _fred_api_key(os.environ, ROOT / ".env")
    if key is None:
        blocked = probe_hy_oas_blocked()
        CACHE_DIR.mkdir(exist_ok=True)
        (CACHE_DIR / "hy_oas.blocked.json").write_text(
            json.dumps({**blocked, "checked_at":
                        datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8")
        print(f"hy_oas: blocked={blocked['blocked']} "
              f"({blocked['evidence'][:60]})")
    else:
        hy, m = fetch_hy_oas(key)
        _save("hy_oas", hy, m)
        (CACHE_DIR / "hy_oas.blocked.json").write_text(
            json.dumps({"blocked": False,
                        "evidence": "acquired via authenticated FRED API "
                                    "(key never stored)",
                        "checked_at":
                        datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8")
        print(f"hy_oas: {len(hy)} obs")


def load_bundle() -> SourceBundle:
    vix = _load("vix")
    blocked: dict[str, str] = {}
    hy_path = CACHE_DIR / "hy_oas.blocked.json"
    if hy_path.exists():
        info = json.loads(hy_path.read_text(encoding="utf-8"))
        if info.get("blocked"):
            blocked["hy_oas"] = "source_blocked"
    return SourceBundle(
        sessions=sorted(vix) if vix else [],
        vix=vix,
        spy=_load("spy"),
        curve_2s10s=_load("curve_2s10s"),
        hy_oas=_load("hy_oas"),
        fed_timeline=FED_TARGET_TIMELINE,
        blocked=blocked,
    )


# ---------------------------------------------------------------------------
# Readiness probe over the 97 candidates
# ---------------------------------------------------------------------------


def run_probe() -> dict[str, Any]:
    candidates = (parse_g1a_candidates(str(G1A_PATH))
                  + parse_g1b_candidates(str(G1B_PATH)))
    bundle = load_bundle()
    rows = [candidate_readiness(c, bundle) for c in candidates]

    by_lane: dict[str, int] = {}
    for r in rows:
        by_lane[r["lane"]] = by_lane.get(r["lane"], 0) + 1
    missing_by_dim: dict[str, int] = {d: 0 for d in DIMENSIONS}
    missing_by_lane_year: dict[str, dict[str, int]] = {}
    for r in rows:
        year = r["event_date"][:4]
        for d in DIMENSIONS:
            if not r["dimensions"][d]["available"]:
                missing_by_dim[d] += 1
                key = f"{r['lane']}/{year}"
                missing_by_lane_year.setdefault(key, {}).setdefault(d, 0)
                missing_by_lane_year[key][d] += 1
    return {
        "candidates": len(rows),
        "by_lane": by_lane,
        "cutoff_resolved": sum(1 for r in rows if r["cutoff_resolved"]),
        "complete_vector": sum(1 for r in rows if r["complete_vector"]),
        "partial_vector": sum(1 for r in rows
                              if 0 < r["dimensions_available"]
                              < len(DIMENSIONS)),
        "missing_by_dimension": missing_by_dim,
        "missing_by_lane_year": dict(sorted(missing_by_lane_year.items())),
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# G2D credit point-in-time evidence extract (candidate-level preservation)
# ---------------------------------------------------------------------------

# Whitelisted evidence-row fields: state INPUTS only, no response vocabulary.
CREDIT_EVIDENCE_FIELDS = ("candidate_id", "lane", "event_date", "cutoff",
                          "obs_date", "value", "series_id",
                          "availability_rule")

EVIDENCE_PATH = ROOT / "stats" / "G2D_CREDIT_POINT_IN_TIME_EVIDENCE.md"


def build_credit_evidence(candidates: Sequence[dict[str, Any]],
                          bundle: SourceBundle) -> dict[str, Any]:
    """Candidate-level HY OAS evidence extract (G2D).

    Availability comes from ``candidate_readiness`` and the value from
    ``latest_eligible`` - the SAME functions the live probe uses; this
    module deliberately contains no second credit calculation path.
    Duplicate candidate ids are counted once; rows sort deterministically.
    """
    rows: list[dict[str, Any]] = []
    missing = 0
    seen: set[str] = set()
    for cand in candidates:
        cid = cand["candidate_id"]
        if cid in seen:
            continue
        seen.add(cid)
        ready = candidate_readiness(cand, bundle)
        if not ready["dimensions"]["credit_hy_oas"]["available"]:
            missing += 1
            continue
        obs_date, value = latest_eligible(bundle.hy_oas, ready["cutoff"],
                                          availability="next_day")
        rows.append({
            "candidate_id": cid,
            "lane": cand["lane"],
            "event_date": cand["event_date"],
            "cutoff": ready["cutoff"],
            "obs_date": obs_date,
            "value": value,
            "series_id": _HY_OAS_SERIES_ID,
            "availability_rule": "next_day",
        })
    rows.sort(key=lambda r: (r["event_date"], r["candidate_id"]))
    return {
        "rows": rows,
        "available": len(rows),
        "source_missing": missing,
        "first_obs_used": min((r["obs_date"] for r in rows), default=None),
        "last_obs_used": max((r["obs_date"] for r in rows), default=None),
    }


def render_credit_evidence(evidence: dict[str, Any],
                           cache_meta: Mapping[str, Any],
                           cache_sha256: str) -> str:
    """Deterministic markdown for the tracked evidence artifact.

    Carries no generation timestamp - only the cache's retrieval
    timestamp - so regeneration from the same cache is byte-identical
    (drift-tested).
    """
    run_date = str(cache_meta["retrieved_at"])[:10]
    L = [
        "# G2D credit point-in-time evidence (Mission G, g0-v1)",
        "",
        "Status: bounded, outcome-blind, candidate-level evidence extract. "
        "The upstream source distributes only a rolling three-year window "
        "of this series, so a future clean re-run may no longer retrieve "
        "the observations used here; this artifact preserves the exact "
        "candidate-level credit inputs in use now.",
        "",
        "This artifact preserves the candidate-level inputs observed in "
        f"the {run_date} acquisition run. It does not preserve or "
        "redistribute the full ICE BofA/FRED series and does not make the "
        "upstream rolling source permanently reproducible.",
        "",
        "## Provenance (artifact level)",
        "",
        f"- series: ICE BofA US High Yield OAS, id `{_HY_OAS_SERIES_ID}`",
        f"- source: {cache_meta['source']}",
        f"- retrieval timestamp: {cache_meta['retrieved_at']}",
        f"- raw-cache SHA256 (`g_state_cache/hy_oas.json`, gitignored): "
        f"`{cache_sha256}`",
        f"- source observations at retrieval: "
        f"{cache_meta.get('observations')} "
        f"({cache_meta.get('first')} through {cache_meta.get('last')})",
        "- selection rule: conservative cutoff = last completed trading "
        "session STRICTLY before the source-pinned event date (VIX session "
        "calendar); eligible observation = latest observation dated "
        "STRICTLY before the cutoff (`next_day` availability class); one "
        "row per available candidate.",
        f"- coverage: {evidence['available']} available / "
        f"{evidence['source_missing']} source_missing (cutoffs before the "
        "surviving source window; disclosed, never proxied)",
        f"- eligible observations used span {evidence['first_obs_used']} "
        f"through {evidence['last_obs_used']}",
        "- generated by `python scripts/g_state_acquisition.py "
        "--emit-credit-evidence` from the same candidate-readiness logic "
        "and `next_day` selector as the live probe (no second credit "
        "calculation path); regeneration from the same cache is "
        "byte-identical and drift-tested.",
        "",
        "This is a preserved candidate-level evidence extract, not an "
        "independent source archive: it records only the 36 per-candidate "
        "input values the readiness pipeline selected, so a reviewer can "
        "audit exactly which credit inputs the substrate used even after "
        "the rolling window advances. No market response of any kind (no "
        "abnormal return, no standardized value, no outcome label, no "
        "state category, no comparison result) appears here.",
        "",
        "## Candidate-level evidence rows",
        "",
        "| candidate_id | lane | event_date | cutoff | obs_date | value | "
        "series_id | availability_rule |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in evidence["rows"]:
        L.append(
            f"| {r['candidate_id']} | {r['lane']} | {r['event_date']} | "
            f"{r['cutoff']} | {r['obs_date']} | {r['value']:.2f} | "
            f"{r['series_id']} | {r['availability_rule']} |")
    return "\n".join(L) + "\n"


def emit_credit_evidence() -> str:
    """Build the extract from live ledgers + cache and write the artifact."""
    import hashlib
    candidates = (parse_g1a_candidates(str(G1A_PATH))
                  + parse_g1b_candidates(str(G1B_PATH)))
    evidence = build_credit_evidence(candidates, load_bundle())
    cache = CACHE_DIR / "hy_oas.json"
    sha = hashlib.sha256(cache.read_bytes()).hexdigest()
    meta = json.loads(cache.read_text(encoding="utf-8"))["meta"]
    text = render_credit_evidence(evidence, meta, sha)
    EVIDENCE_PATH.write_text(text, encoding="utf-8", newline="\n")
    return (f"credit evidence: {evidence['available']} rows "
            f"({evidence['source_missing']} source_missing) -> "
            f"{EVIDENCE_PATH.relative_to(ROOT)}")


def render_probe(report: dict[str, Any]) -> str:
    L = ["G2 state-source readiness probe (outcome-blind)", ""]
    L.append(f"candidates: {report['candidates']} by lane {report['by_lane']}")
    L.append(f"cutoff resolved: {report['cutoff_resolved']}/"
             f"{report['candidates']}")
    L.append(f"complete state vector (5/5): {report['complete_vector']} | "
             f"partial: {report['partial_vector']}")
    L.append("missing by dimension:")
    for d, n in report["missing_by_dimension"].items():
        L.append(f"  {d}: {n}")
    L.append("missing by lane/year (dimension: count):")
    for key, dims in report["missing_by_lane_year"].items():
        L.append(f"  {key}: {dims}")
    return "\n".join(L)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="G2 state acquisition substrate (zero-cost sources; "
                    "no events.db or price_cache mutation).")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--emit-credit-evidence", action="store_true")
    args = parser.parse_args(argv)
    if args.fetch:
        run_fetch()
    if args.emit_credit_evidence:
        print(emit_credit_evidence())
    if args.probe:
        report = run_probe()
        if args.json:
            print(json.dumps(report, indent=1, sort_keys=True))
        else:
            print(render_probe(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
