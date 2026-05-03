"""Versioned (channel, region) → benchmark ticker registry.

Why this exists
---------------
The core macro composers (``shock_decomposition`` / ``cross_asset_coherence`` /
``real_yield_context``) have always resolved their channel benchmarks
against hard-coded US tickers — 10Y Treasury for rates, DXY for FX,
CL for oil, and so on.  That was fine when every event in the archive
was US-tape-driven, but the coverage has been expanding: ECB
decisions, China export curbs, EM funding shocks.  For those we want
the same engine paths (shock / coherence / macro-surprise join) to be
able to resolve a Europe- or Asia-specific channel proxy instead of
always asking "what did the 10Y do?".

This module is that lookup layer.  It is NOT an execution path — it
doesn't fetch data, it doesn't replace the existing
``_CHANNEL_BENCHMARK_TICKER`` / ``_COHERENCE_CHANNEL_BENCHMARK`` maps
inside the composers.  It is a thin, deterministic
``(channel, region)`` → ``ticker`` table plus validation helpers.
Callers ready to light up non-US paths can opt in to
``get_channel_benchmark(channel, region=...)``; composers that don't
pass a region keep today's behaviour (``americas`` default).

Registry discipline
-------------------
* **Versioned.**  ``REGISTRY_VERSION`` is bumped whenever the shape or
  ticker choices change.  Downstream caches that key on this layer
  can invalidate on mismatch rather than persist a stale mapping.
* **Closed enums.**  ``CHANNEL_IDS`` and ``REGION_IDS`` are frozen
  tuples; the region vocabulary re-exports
  ``feed_registry.ALL_REGIONS`` so asset coverage and news coverage
  share one taxonomy and can be tested for drift (see
  ``tests/test_asset_registry.py``).
* **Grounded in quarantine.**  Every ticker this module returns must
  also appear in ``benchmark_quarantine.BENCHMARK_REGISTRY`` — that's
  enforced by ``_validate_registry_invariants`` at import time.  A
  channel benchmark with no quarantine thresholds is a silent
  reliability hazard and this module refuses to surface it.
* **No healthy-path edits.**  The existing composer dicts are not
  touched.  ``get_channel_benchmark("rates", "americas")`` is
  guaranteed to equal the US ticker those composers already use.
"""

from __future__ import annotations

from typing import Optional

from benchmark_quarantine import BENCHMARK_REGISTRY
from feed_registry import ALL_REGIONS


REGISTRY_VERSION: int = 1


# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------
# Channels mirror the six grouped channels in ``cross_asset_coherence``.
# Regions are the same keys ``feed_registry`` uses for RSS filtering — we
# reuse rather than invent a parallel taxonomy, and ``REGION_IDS`` below
# stays in sync with ``feed_registry.ALL_REGIONS`` via a test invariant.

CHANNEL_IDS: tuple[str, ...] = (
    "rates",
    "fx",
    "equities",
    "commodities",
    "credit",
    "vol",
)

REGION_IDS: tuple[str, ...] = tuple(sorted(ALL_REGIONS))


# ---------------------------------------------------------------------------
# The table — (channel, region) → benchmark ticker
# ---------------------------------------------------------------------------
# Ticker choices:
#   rates        — US 10Y via ^TNX; non-US via BWX (G7 ex-US duration
#                  proxy ETF; yfinance does not serve a clean yield
#                  index for EU/UK/JP).
#   fx           — DXY for US / global default; regional majors keyed
#                  by the primary cross (EURUSD for Europe, USDJPY for
#                  Asia, USDMXN for LatAm, USDBRL as the Brazil anchor).
#   equities     — SPY US · ^STOXX50E Europe · ^N225 Asia · ^GDAXI
#                  Germany-lean Europe fallback · EEM emerging markets
#                  (south_asia, latin_america, middle_east, africa).
#   commodities  — WTI (CL) for Americas · Brent (BZ=F) globally / EU /
#                  Middle East · Copper (HG=F) Asia (China-led demand).
#   credit       — HYG US · EMB for emerging-market sovereign spreads ·
#                  LQD as the IG fallback for Europe.
#   vol          — VIX globally (no regional vol index has the same
#                  reliability from yfinance).

_CHANNEL_REGION_BENCHMARK: dict[str, dict[str, str]] = {
    "rates": {
        # Americas / global default uses the same "10Y" symbolic key the
        # existing composers hard-code so the invariant test can assert
        # byte-equal output against ``_CHANNEL_BENCHMARK_TICKER``.
        "global":        "10Y",
        "americas":      "10Y",
        "europe":        "BWX",
        "asia":          "BWX",
        "south_asia":    "BWX",
        "middle_east":   "BWX",
        "latin_america": "EMB",
        "africa":        "EMB",
    },
    "fx": {
        "global":        "DXY",
        "americas":      "DXY",
        "europe":        "EURUSD=X",
        "asia":          "USDJPY=X",
        "south_asia":    "USDJPY=X",
        "middle_east":   "DXY",
        "latin_america": "USDMXN=X",
        "africa":        "DXY",
    },
    "equities": {
        "global":        "SPY",
        "americas":      "SPY",
        "europe":        "^STOXX50E",
        "asia":          "^N225",
        "south_asia":    "EEM",
        "middle_east":   "EEM",
        "latin_america": "EEM",
        "africa":        "EEM",
    },
    "commodities": {
        "global":        "CL",
        "americas":      "CL",
        "europe":        "BZ=F",
        "asia":          "HG=F",
        "south_asia":    "BZ=F",
        "middle_east":   "BZ=F",
        "latin_america": "CL",
        "africa":        "BZ=F",
    },
    "credit": {
        "global":        "HYG",
        "americas":      "HYG",
        "europe":        "LQD",
        "asia":          "EMB",
        "south_asia":    "EMB",
        "middle_east":   "EMB",
        "latin_america": "EMB",
        "africa":        "EMB",
    },
    "vol": {
        "global":        "VIX",
        "americas":      "VIX",
        "europe":        "VIX",
        "asia":          "VIX",
        "south_asia":    "VIX",
        "middle_east":   "VIX",
        "latin_america": "VIX",
        "africa":        "VIX",
    },
}


# ---------------------------------------------------------------------------
# Lookup API
# ---------------------------------------------------------------------------

def get_channel_benchmark(
    channel: str, region: str = "americas",
) -> str:
    """Return the benchmark ticker for ``(channel, region)``.

    Defaults to the US / ``americas`` mapping so callers that don't
    pass a region get the same answer the existing composers hard-code
    today.  Raises ``ValueError`` on unknown ``channel`` or ``region``.
    """
    if channel not in _CHANNEL_REGION_BENCHMARK:
        raise ValueError(
            f"unknown channel={channel!r}; allowed: {list(CHANNEL_IDS)}"
        )
    region_map = _CHANNEL_REGION_BENCHMARK[channel]
    if region not in region_map:
        raise ValueError(
            f"unknown region={region!r} for channel={channel!r}; "
            f"allowed: {list(REGION_IDS)}"
        )
    return region_map[region]


def list_channel_tickers(channel: str) -> list[str]:
    """Return every ticker this channel can resolve to, sorted, unique."""
    if channel not in _CHANNEL_REGION_BENCHMARK:
        raise ValueError(f"unknown channel={channel!r}")
    return sorted(set(_CHANNEL_REGION_BENCHMARK[channel].values()))


def list_regions_for_channel(channel: str) -> list[str]:
    """Return the regions for which ``channel`` has a benchmark ticker."""
    if channel not in _CHANNEL_REGION_BENCHMARK:
        raise ValueError(f"unknown channel={channel!r}")
    return sorted(_CHANNEL_REGION_BENCHMARK[channel].keys())


def is_supported(channel: str, region: str) -> bool:
    """True when ``(channel, region)`` resolves to a ticker."""
    return (
        channel in _CHANNEL_REGION_BENCHMARK
        and region in _CHANNEL_REGION_BENCHMARK[channel]
    )


# ---------------------------------------------------------------------------
# Import-time invariants.  A channel benchmark that isn't quarantined is
# a silent reliability hazard (no hard_cap, no outlier guard) — we refuse
# to let one ship by failing fast at import.
# ---------------------------------------------------------------------------

def _validate_registry_invariants() -> None:
    """Run at module import — see docstring."""
    missing_quarantine: list[tuple[str, str, str]] = []
    for channel, region_map in _CHANNEL_REGION_BENCHMARK.items():
        if channel not in CHANNEL_IDS:
            raise AssertionError(
                f"asset_registry: channel {channel!r} not in CHANNEL_IDS"
            )
        for region, ticker in region_map.items():
            if region not in REGION_IDS:
                raise AssertionError(
                    f"asset_registry: region {region!r} not in REGION_IDS"
                )
            key = ticker.strip().upper()
            if key not in BENCHMARK_REGISTRY:
                missing_quarantine.append((channel, region, ticker))
    if missing_quarantine:
        raise AssertionError(
            "asset_registry: the following (channel, region, ticker) "
            "triples have no quarantine thresholds in BENCHMARK_REGISTRY: "
            f"{missing_quarantine}"
        )


_validate_registry_invariants()
