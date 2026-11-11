"""A small registry; the model selects IDs, never executable expressions.

An entry with a `source` is bound to one provider series; data for it comes only from that
source. Entries without a source are concept IDs: no provider supplies them, and they are never
silently re-pointed to another series. Every consumer of the bindings names its provider
(source_bound), so adding a provider never changes what another one serves.

The fictional demonstration series of the offline demo (fixtures/demo-market.json, invented by
demo_market.py) have their own table: resolve() reads it so the two showcase replays can be
measured, but registry_ids() and source_bound() never list it, and no research hypothesis may
name a demo ID (schema.Hypothesis refuses it).
"""
from dataclasses import dataclass
import re

FRED = "fred"  # The FRED API (DGS2, DGS10).
BOARD_H15 = "board-h15"  # The Federal Reserve Board's H.15 release package, kept and validated locally.
PROVIDERS = (FRED, BOARD_H15)


@dataclass(frozen=True)
class Observable:
    id: str
    unit: str
    measurement: str
    anchor_policy: str
    benchmark: str | None = None
    requires_contract: bool = False
    source: str | None = None  # Provider series binding, e.g. "fred:DGS10".


_FIXED = {
    "yield:us2y": Observable("yield:us2y", "bp", "yield_bp", "next_observation"),
    "yield:us10y": Observable("yield:us10y", "bp", "yield_bp", "next_observation"),
    "index:dxy": Observable("index:dxy", "%", "return_pct", "next_observation"),
    "fx:usdils": Observable("fx:usdils", "%", "return_pct", "next_observation"),
    "futures:wti": Observable("futures:wti", "%", "return_pct", "next_observation", requires_contract=True),
    "futures:brent": Observable("futures:brent", "%", "return_pct", "next_observation", requires_contract=True),
    # Treasury constant-maturity yields (H.15 via FRED, source U.S. Treasury), measured by date only.
    "yield:ust2y_cmt": Observable("yield:ust2y_cmt", "bp", "yield_bp", "daily_ny_date", source="fred:DGS2"),
    "yield:ust10y_cmt": Observable("yield:ust10y_cmt", "bp", "yield_bp", "daily_ny_date", source="fred:DGS10"),
    # The same constant-maturity yields from the Board's H.15 release package (source U.S. Treasury), measured by
    # date only. Separate IDs: a hypothesis bound to FRED is never re-pointed to the Board, nor the reverse.
    "yield:ust2y_cmt_h15": Observable("yield:ust2y_cmt_h15", "bp", "yield_bp", "daily_ny_date",
                                      source=f"{BOARD_H15}:RIFLGFCY02_N.B"),
    "yield:ust10y_cmt_h15": Observable("yield:ust10y_cmt_h15", "bp", "yield_bp", "daily_ny_date",
                                       source=f"{BOARD_H15}:RIFLGFCY10_N.B"),
}
# FICTIONAL demonstration series for the offline demo only; kept apart from the registry above.
_DEMO = {
    "demo:rate": Observable("demo:rate", "bp", "yield_bp", "next_observation"),
    "demo:fx-index": Observable("demo:fx-index", "%", "return_pct", "next_observation"),
}
_FAMILY = re.compile(r"(us_equity|us_etf):([A-Z][A-Z0-9.-]{0,9})")


def resolve(observable_id: str) -> Observable:
    if observable_id in _FIXED:
        return _FIXED[observable_id]
    if observable_id in _DEMO:
        return _DEMO[observable_id]
    if _FAMILY.fullmatch(observable_id):
        return Observable(observable_id, "% AR", "market_model", "us_regular_session", "us_etf:SPY")
    raise ValueError(f"Unknown observable: {observable_id}")


def registry_ids() -> tuple[str, ...]:
    """The registry's entries; the fictional demonstration IDs are not among them."""
    return tuple(_FIXED) + ("us_equity:<TICKER>", "us_etf:<TICKER>")


def is_demo(observable_id: str) -> bool:
    """True for a fictional demonstration series of the offline demo, which is never research evidence."""
    return observable_id in _DEMO


def binding(observable_id: str) -> tuple[str, str] | None:
    """(provider, provider series ID) of a source-bound observable; None for a concept or demonstration ID."""
    source = resolve(observable_id).source
    if source is None:
        return None
    provider, series_id = source.split(":", 1)
    return provider, series_id


def source_bound(provider: str) -> dict[str, str]:
    """Observable ID -> provider series ID for every entry bound to the named provider."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown market data provider: {provider}")
    return {key: entry.source.split(":", 1)[1] for key, entry in _FIXED.items()
            if entry.source and entry.source.split(":", 1)[0] == provider}
