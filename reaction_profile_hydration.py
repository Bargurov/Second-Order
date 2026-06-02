"""Per-ticker reaction-profile hydration from the price-cache layer.

Composes one per-ticker reaction-profile dict by:

  1. Reading raw close series for the ticker and its benchmark from
     the SQLite ``price_cache`` table (read-only, no provider fetch).
  2. Forwarding the resulting ``closes`` / ``benchmark_closes`` plus
     the saved-row flags (``stale``, ``same_day_fallback``,
     ``validation_quality``) into the pure
     :func:`reaction_profile.compute_reaction_profile`.

Read-only contract
------------------
* No provider call, no ``yfinance`` import, no ``market_data`` import.
* No DB write, no row mutation.
* Never raises on malformed input — collapses to the unscorable shape.

Both data sources are seam-injected so tests can patch them in without
touching SQLite.  The defaults are
:func:`price_cache.read_window_no_fetch` and
:func:`market_check.resolve_benchmark`, both already pure.

See ``docs/reaction_profile_hydration_plan.md`` for the data-source
audit and ``docs/reaction_profile_design.md`` for the field contract.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any, Callable, Optional, Sequence

import pandas as pd

from reaction_profile import compute_reaction_profile


# Window we read out of cache: 1 anchor bar + 61 forward bars covers the
# 60d horizon.  Going further is wasted SQL with no upside for the
# composer.
_FORWARD_BARS: int = 62


CacheReader = Callable[..., Optional[pd.DataFrame]]
BenchmarkResolver = Callable[[str], tuple[str, str]]


def _default_cache_reader() -> CacheReader:
    # Late import keeps the hydrator importable in environments where
    # the SQLite layer is not bootstrapped (and lets tests inject a
    # fake reader without paying the cache-import cost).
    from price_cache import read_window_no_fetch
    return read_window_no_fetch


def _default_benchmark_resolver() -> BenchmarkResolver:
    # ``market_check.resolve_benchmark`` is a pure dict lookup; the
    # surrounding module is heavy but the function itself does no I/O
    # and triggers no provider import on call.
    from market_check import resolve_benchmark
    return resolve_benchmark


def _coerce_anchor(
    event_date: Any, fallback_anchor: Any,
) -> Optional[str]:
    """Pick an anchor ISO date string and snap it to a real US trading
    session, mirroring the convention :func:`market_check._fetch_since`
    uses (``_clamp_to_market_date``).  Snapping here is what makes the
    hydrated profile bit-comparable to a profile produced in-process at
    market-check time — without it, an event saved on a Saturday would
    anchor on Monday's close in hydration and on Friday's close in
    market_check, producing different ``return_5d`` values for the
    same event.
    """
    for candidate in (event_date, fallback_anchor):
        if not isinstance(candidate, str) or not candidate:
            continue
        # Strip any time component so a "YYYY-MM-DDTHH:MM:SS" timestamp
        # round-trips through ``date.fromisoformat``.
        head = candidate[:10]
        try:
            _date.fromisoformat(head)
        except ValueError:
            continue
        # Late import — ``market_check`` carries a heavy import graph,
        # but the helper itself is pure and triggers no provider call.
        try:
            from market_check import _clamp_to_market_date
            return _clamp_to_market_date(head)
        except Exception:
            return head
    return None


def _closes_from_frame(frame: Optional[pd.DataFrame]) -> list[float]:
    """Materialise a cache DataFrame into a plain list of floats.

    Strips NaNs at the front (they would invalidate the anchor) and
    truncates to ``_FORWARD_BARS`` so the composer never scans more
    than it needs.
    """
    if frame is None or frame.empty or "Close" not in frame.columns:
        return []
    series = frame["Close"].dropna()
    if series.empty:
        return []
    out = [float(v) for v in series.iloc[:_FORWARD_BARS].tolist()]
    return out


def _quarantined_horizons(saved_ticker: dict) -> set[str]:
    """Translate the saved per-ticker ``validation_quality`` into a set
    of quarantined horizon suffixes.

    Today the saved row only carries a single benchmark-health label
    (``"ok" / "warn" / "quarantined"``).  Until horizon-level quarantine
    is persisted explicitly we apply the conservative all-or-nothing
    rule from ``docs/reaction_profile_hydration_plan.md`` §8.
    """
    quality = saved_ticker.get("validation_quality")
    if isinstance(quality, str) and quality.lower() == "quarantined":
        return {"1d", "5d", "20d", "60d"}
    return set()


# ---------------------------------------------------------------------------
# Hydration-status enum — operator-facing per-ticker triage label
# ---------------------------------------------------------------------------
# Distinct from ``reaction_profile_basis`` (the composer's *scoring shape*
# label, e.g. ``forward_anchored``).  ``hydration_status`` answers a
# different question: "did we get useful numbers, and if not, why?"
#
#   hydrated           — at least one ``return_*`` populated; chartable.
#   cache_miss         — zero cache rows for this ticker / anchor.
#   insufficient_window — anchor row only (or other <2 bar shape); the
#                        composer ran but no horizon could be computed.
#   stale              — saved row carries ``stale=True`` (delisted /
#                        halted).  Forward-looking fields are nulled
#                        regardless of cache state.
#   same_day_fallback  — saved row carries ``same_day_fallback=True``
#                        AND the composer was unable to extract a 1d
#                        return (rare; the usual SDF row populates r1d
#                        and lands in ``hydrated``).
HYDRATION_STATUSES: tuple[str, ...] = (
    "hydrated",
    "cache_miss",
    "insufficient_window",
    "stale",
    "same_day_fallback",
)


def _derive_hydration_status(
    *,
    stale_flag: bool,
    sdf_flag: bool,
    closes_count: int,
    profile: dict,
) -> str:
    """Map the hydrator's intermediate state onto the operator-facing enum.

    Precedence (top-down):
      1. ``stale``  — delisted ticker overrides everything.
      2. ``cache_miss`` — zero cache rows; composer wasn't given anything
                          to chew on.  Folds in missing symbol / anchor
                          (both produce ``closes_count == 0`` upstream).
      3. ``hydrated`` — composer ran AND any return_* populated.
      4. ``same_day_fallback`` — SDF flag was set but the composer
                                 couldn't extract a 1d return.
      5. ``insufficient_window`` — fallback for any other "ran but
                                   produced nothing" path.
    """
    if stale_flag:
        return "stale"
    if closes_count == 0:
        return "cache_miss"
    for h in ("1d", "5d", "20d", "60d"):
        if profile.get(f"return_{h}") is not None:
            return "hydrated"
    if sdf_flag:
        return "same_day_fallback"
    return "insufficient_window"


def hydrate_per_ticker_profile(
    saved_ticker: dict,
    *,
    event_date: Optional[str],
    benchmark_resolver: Optional[BenchmarkResolver] = None,
    cache_reader: Optional[CacheReader] = None,
) -> dict:
    """Compose one per-ticker reaction-profile entry from cache rows.

    ``saved_ticker`` is the persisted ``market_tickers[i]`` dict.  The
    function reads ``stale``, ``same_day_fallback``,
    ``validation_quality``, ``symbol``, and ``anchor_date`` off the row
    — every other field is ignored.  Output dict shape exactly matches
    what :func:`reaction_profile.compute_reaction_profile` returns plus
    a leading ``symbol`` key and the operator-facing
    ``hydration_status`` triage label (see :data:`HYDRATION_STATUSES`).

    Both data sources are injectable: tests pass canned readers to
    avoid touching SQLite.  Defaults read from the on-disk price cache
    via :func:`price_cache.read_window_no_fetch` (no provider call).
    """
    # Normalise inputs — never raise on malformed dict / missing keys.
    if not isinstance(saved_ticker, dict):
        saved_ticker = {}
    raw_symbol = saved_ticker.get("symbol")
    symbol = raw_symbol if isinstance(raw_symbol, str) and raw_symbol else None

    reader = cache_reader or _default_cache_reader()
    resolver = benchmark_resolver or _default_benchmark_resolver()

    # Anchor — event_date wins; fall back to the saved row's anchor.
    anchor = _coerce_anchor(event_date, saved_ticker.get("anchor_date"))

    # Saved-row flags propagate verbatim to the pure composer.
    stale_flag = bool(saved_ticker.get("stale"))
    sdf_flag   = bool(saved_ticker.get("same_day_fallback"))
    quarantined = _quarantined_horizons(saved_ticker)

    # Pull bars only when we have a real anchor and a real symbol.
    closes: list[float] = []
    bench_closes: list[float] = []
    if symbol and anchor:
        try:
            ticker_frame = reader(symbol, start=anchor, auto_adjust=False)
        except Exception:
            ticker_frame = None
        closes = _closes_from_frame(ticker_frame)

        if closes:
            try:
                bench_etf, _sector = resolver(symbol)
            except Exception:
                bench_etf = None
            if isinstance(bench_etf, str) and bench_etf:
                try:
                    bench_frame = reader(
                        bench_etf, start=anchor, auto_adjust=False,
                    )
                except Exception:
                    bench_frame = None
                bench_closes = _closes_from_frame(bench_frame)

    profile = compute_reaction_profile(
        closes if closes else None,
        benchmark_closes=bench_closes if bench_closes else None,
        stale=stale_flag,
        same_day_fallback=sdf_flag,
        benchmark_quarantined_horizons=quarantined,
    )
    hydration_status = _derive_hydration_status(
        stale_flag=stale_flag,
        sdf_flag=sdf_flag,
        closes_count=len(closes),
        profile=profile,
    )
    return {
        "symbol":           symbol,
        "hydration_status": hydration_status,
        **profile,
    }


def build_reaction_profile_v1(event: dict) -> dict:
    """Compose the ``reaction_profile_v1`` block for a saved event.

    Read-only over the saved event row.  For each saved
    ``market_tickers`` entry the helper hands the per-ticker dict to
    :func:`hydrate_per_ticker_profile`, which reads the raw close window
    from the SQLite price-cache table and feeds it into the pure
    :func:`reaction_profile.compute_reaction_profile`.  The hydrator is
    read-only over the cache: it never plans or triggers a provider
    fetch (see ``docs/reaction_profile_hydration_plan.md`` §6 / §7).

    ``available`` is True when at least one ticker hydrated to a
    non-unscorable basis; consumers can branch on it without
    re-deriving the cause.

    Surfaced by ``GET /events/{id}`` and by the cached
    ``POST /analyze {event_id}`` restore (``api._build_cached_response``)
    so both saved-event surfaces read identically.
    """
    raw_tickers = event.get("market_tickers")
    tickers: list[dict] = (
        list(raw_tickers) if isinstance(raw_tickers, list) else []
    )
    event_date = event.get("event_date")
    per_ticker: list[dict] = []
    for t in tickers:
        if not isinstance(t, dict):
            # Malformed entry — skip.  Composer never raises on this
            # path, but we don't want to attach a profile to a row we
            # can't even name.
            continue
        per_ticker.append(
            hydrate_per_ticker_profile(t, event_date=event_date)
        )

    # ``available`` means at least one per-ticker entry hydrated to a
    # real numeric signal.  Aligned with the per-ticker
    # ``hydration_status`` enum: status="hydrated" iff any return_* is
    # non-null.
    status_counts: dict[str, int] = {s: 0 for s in HYDRATION_STATUSES}
    for entry in per_ticker:
        s = entry.get("hydration_status")
        if isinstance(s, str) and s in status_counts:
            status_counts[s] += 1

    n_hydrated = status_counts["hydrated"]
    total = len(per_ticker)
    available = n_hydrated > 0

    if total == 0:
        reason = "no market_tickers on this event"
    else:
        # Always emit a per-status breakdown so consumers can see why
        # the block reads the way it does without re-deriving the
        # cause.
        bits: list[str] = []
        for s in HYDRATION_STATUSES:
            n = status_counts[s]
            if n > 0:
                bits.append(f"{n} {s}")
        breakdown = ", ".join(bits) if bits else f"{total} unknown"
        if available:
            reason = (
                f"hydrated {n_hydrated}/{total} per-ticker profile(s) "
                f"from cached close windows ({breakdown})"
            )
        else:
            reason = (
                f"0/{total} per-ticker profile(s) hydrated; per-ticker "
                f"status: {breakdown}"
            )

    return {
        "available": available,
        "reason":    reason,
        "tickers":   per_ticker,
        "n_tickers": len(per_ticker),
    }


__all__ = [
    "hydrate_per_ticker_profile",
    "build_reaction_profile_v1",
    "HYDRATION_STATUSES",
]
