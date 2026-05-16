"""
tools/seed_showcase_events.py

Local-only showcase seeder.

Inserts a small set of clearly-labeled demo events into the local
SQLite events table so a fresh install (or a quiet news day) can
demo the Today / Weekly / Persistent mover surfaces without waiting
for live news + analysis.

Demo markers (defense-in-depth):

  * headline prefix ``[DEMO] ``        — visible to any UI surface
  * ``model = 'showcase_seed_v1'``     — programmatic filter / cleanup
  * ``notes  = 'SHOWCASE/DEMO seed …'`` — provenance for archive readers

Run:

    python -m tools.seed_showcase_events            # insert + verify
    python -m tools.seed_showcase_events --clear    # delete demo rows
    python -m tools.seed_showcase_events --dry-run  # show without writing

The verification step calls the local /movers/today, /movers/weekly,
/movers/persistent endpoints (via FastAPI's TestClient — no HTTP
server needed) and reports which DEMO headlines surfaced on each
surface.  The script does NOT loosen any production gate; rows that
fail the live persistent high-impact rule will simply not appear on
that surface and the verification step will say so.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402

DEMO_MODEL_TAG = "showcase_seed_v1"
DEMO_HEADLINE_PREFIX = "[DEMO] "
DEMO_NOTES = "SHOWCASE/DEMO seed — not live data; safe to clear."


def _ts(hours_ago: float) -> str:
    return (datetime.now() - timedelta(hours=hours_ago)).isoformat(timespec="seconds")


def _date(days_ago: int) -> str:
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _ticker(
    symbol: str,
    role: str,
    *,
    return_5d: float,
    return_1d: float | None = None,
    direction: str = "supports ↑",
    sector: str = "Energy",
    validation: str = "alpha_support",
) -> dict:
    """Build one ticker block with the fields ``_build_mover_summary``
    and the ranking layers actually read.  Defaults match a clean
    primary confirmation: alpha-supportive, supportive direction tag,
    real return_5d magnitude.
    """
    block: dict = {
        "symbol": symbol,
        "role": role,
        "return_5d": return_5d,
        "return_20d": return_5d * 1.1,
        "direction_tag": direction,
        "spark": [],
        "anchor_date": _date(2),
        "benchmark_sector": sector,
        "validation_quality": validation,
    }
    if return_1d is not None:
        block["return_1d"] = return_1d
    return block


def _persistence_signal(repricing_state: str = "grind") -> dict:
    """A persistence_signal block whose repricing state lifts the
    persistence_quality factor in ``compute_conviction_rank``.

    ``grind`` / ``gap_and_hold`` / ``second_leg`` all sit at +0.15+
    quality so they push the conviction class to ``conviction``
    when paired with a primary-confirmation evidence tier.
    """
    return {
        "status": "active",
        "days_elapsed": 5,
        "repricing": {
            "state": repricing_state,
            "rationale": "Demo seed — repricing state hard-coded for showcase",
        },
    }


def _seed_event(
    *,
    headline: str,
    timestamp_hours_ago: float,
    event_date_days_ago: int,
    mechanism_summary: str,
    mechanism_family: str,
    transmission_chain: list[str],
    transmission_path: list[str],
    beneficiaries: list[str],
    losers: list[str],
    market_tickers: list[dict],
    persistence_signal_state: str | None = None,
    confidence: str = "high",
    minimum_proof_set: list[dict] | None = None,
    key_falsifiers: list[dict] | None = None,
) -> dict:
    """Build one demo event record marked as showcase data."""
    event: dict = {
        "headline": DEMO_HEADLINE_PREFIX + headline,
        "stage": "realized",
        "persistence": "high",
        "confidence": confidence,
        "event_date": _date(event_date_days_ago),
        "timestamp": _ts(timestamp_hours_ago),
        "last_market_check_at": _ts(0.25),
        "model": DEMO_MODEL_TAG,
        "notes": DEMO_NOTES,
        "what_changed": "Demo: " + mechanism_summary,
        "mechanism_summary": mechanism_summary,
        "mechanism_family": mechanism_family,
        "transmission_chain": transmission_chain,
        "transmission_path": transmission_path,
        "beneficiaries": beneficiaries,
        "losers": losers,
        "assets_to_watch": list({t["symbol"] for t in market_tickers}),
        "primary_assets": [t["symbol"] for t in market_tickers if t.get("role") == "beneficiary"][:3],
        "secondary_assets": [],
        "hedge_or_signal_assets": [],
        "minimum_proof_set": minimum_proof_set or [],
        "key_falsifiers": key_falsifiers or [],
        "market_tickers": market_tickers,
        "market_note": "Demo seed — market tickers reflect a hand-picked illustrative move.",
        "low_signal": 0,
    }
    if persistence_signal_state:
        event["persistence_signal"] = _persistence_signal(persistence_signal_state)
    return event


# ---------------------------------------------------------------------------
# Seed catalogue — three rows per surface
# ---------------------------------------------------------------------------

def _proof_set(symbols: list[str]) -> list[dict]:
    """Minimum proof entries that match the seed's beneficiary tickers
    so ``proof_status`` can read as confirming on observed tape.
    """
    return [
        {
            "claim": f"{sym} should rally on the named transmission",
            "evidence_kind": "ticker_move",
            "ticker": sym,
            "direction": "up",
        }
        for sym in symbols
    ]


def _falsifier_set(symbols: list[str]) -> list[dict]:
    return [
        {
            "claim": f"{sym} reversing >2% would invalidate the read",
            "evidence_kind": "ticker_move",
            "ticker": sym,
            "direction": "down",
        }
        for sym in symbols
    ]


TODAY_SEEDS = [
    dict(
        headline="OPEC announces surprise oil production cut",
        timestamp_hours_ago=2.0,
        event_date_days_ago=0,
        mechanism_summary=(
            "OPEC supply tightening lifts crude prices; energy "
            "producers benefit, transport / chemicals exposed to "
            "input-cost pass-through fade."
        ),
        mechanism_family="commodity_squeeze",
        transmission_chain=[
            "OPEC quota cut",
            "Crude futures bid",
            "Energy equities outperform",
            "Transport / chemicals lag",
        ],
        transmission_path=["USO", "XLE", "JETS"],
        beneficiaries=["XLE", "USO", "OXY"],
        losers=["JETS", "DAL"],
        market_tickers=[
            _ticker("USO", "beneficiary", return_5d=4.8, return_1d=2.1),
            _ticker("XLE", "beneficiary", return_5d=3.6, return_1d=1.5),
            _ticker("OXY", "beneficiary", return_5d=5.2, return_1d=2.4),
            _ticker("JETS", "loser", return_5d=-2.1, return_1d=-1.0,
                    direction="supports ↓", sector="Industrials"),
        ],
    ),
    dict(
        headline="China announces semiconductor export curbs",
        timestamp_hours_ago=6.0,
        event_date_days_ago=0,
        mechanism_summary=(
            "China tightens semiconductor export controls; US "
            "chipmakers face pricing power on constrained supply, "
            "diversified hardware vendors with China revenue exposure "
            "see margin pressure."
        ),
        mechanism_family="export_controls",
        transmission_chain=[
            "China export curb announced",
            "Constrained chip supply",
            "US chipmakers hold pricing power",
            "China-exposed hardware compresses",
        ],
        transmission_path=["SOXX", "SMH", "AAPL"],
        beneficiaries=["SOXX", "SMH", "NVDA"],
        losers=["AAPL"],
        market_tickers=[
            _ticker("SOXX", "beneficiary", return_5d=3.2, return_1d=1.4,
                    sector="Technology"),
            _ticker("SMH", "beneficiary", return_5d=3.8, return_1d=1.6,
                    sector="Technology"),
            _ticker("NVDA", "beneficiary", return_5d=4.5, return_1d=2.0,
                    sector="Technology"),
        ],
    ),
    dict(
        headline="Brazil central bank holds rates above expectations",
        timestamp_hours_ago=18.0,
        event_date_days_ago=0,
        mechanism_summary=(
            "BCB holds Selic above expectations; BRL bid on relative "
            "carry, EM-LatAm rates duration trades take a positive "
            "lift, USD weakens against BRL on the day."
        ),
        mechanism_family="rates_policy",
        transmission_chain=[
            "BCB hawkish hold",
            "BRL strengthens on carry",
            "EM rates duration repriced",
        ],
        transmission_path=["EWZ", "BRZU"],
        beneficiaries=["EWZ", "BRZU"],
        losers=[],
        market_tickers=[
            _ticker("EWZ", "beneficiary", return_5d=2.6, return_1d=1.1,
                    sector="EM"),
            _ticker("BRZU", "beneficiary", return_5d=4.9, return_1d=2.2,
                    sector="EM"),
        ],
    ),
]


WEEKLY_SEEDS = [
    dict(
        headline="EU agrees on critical minerals supply chain pact",
        timestamp_hours_ago=72.0,
        event_date_days_ago=3,
        mechanism_summary=(
            "EU diversification away from single-source rare-earth "
            "supply lifts non-China critical minerals miners; legacy "
            "China-routed supply chains compress on relative loss."
        ),
        mechanism_family="supply_chain_realignment",
        transmission_chain=[
            "EU minerals pact ratified",
            "Non-China miners bid",
            "Legacy supply routes compressed",
        ],
        transmission_path=["LIT", "REMX"],
        beneficiaries=["LIT", "REMX", "MP"],
        losers=[],
        market_tickers=[
            _ticker("LIT", "beneficiary", return_5d=3.1, return_1d=0.8,
                    sector="Materials"),
            _ticker("REMX", "beneficiary", return_5d=4.4, return_1d=1.2,
                    sector="Materials"),
            _ticker("MP", "beneficiary", return_5d=6.8, return_1d=2.0,
                    sector="Materials"),
        ],
    ),
    dict(
        headline="Japan intervenes in FX market to defend yen",
        timestamp_hours_ago=120.0,
        event_date_days_ago=5,
        mechanism_summary=(
            "MoF intervention strengthens JPY; Japanese exporters "
            "compress on translation risk, JPY-funded carry trades "
            "unwind."
        ),
        mechanism_family="fx_intervention",
        transmission_chain=[
            "MoF JPY-buy intervention",
            "JPY strengthens vs USD",
            "Exporters compress on translation",
        ],
        transmission_path=["FXY", "EWJ"],
        beneficiaries=["FXY"],
        losers=["EWJ"],
        market_tickers=[
            _ticker("FXY", "beneficiary", return_5d=2.4, return_1d=0.9,
                    sector="FX"),
            _ticker("EWJ", "loser", return_5d=-3.0, return_1d=-1.4,
                    direction="supports ↓", sector="EM"),
        ],
    ),
    dict(
        headline="US Treasury auction sees weak foreign demand",
        timestamp_hours_ago=96.0,
        event_date_days_ago=4,
        mechanism_summary=(
            "Indirect bidder weakness lifts term premium; long-duration "
            "Treasuries compress on supply concession, USD trades "
            "softer on rates-uncertainty premium."
        ),
        mechanism_family="rates_supply",
        transmission_chain=[
            "Weak indirect take-down",
            "Term premium repriced",
            "Long-duration Treasuries pressured",
        ],
        transmission_path=["TLT", "UUP"],
        beneficiaries=["TBT"],
        losers=["TLT"],
        market_tickers=[
            _ticker("TLT", "loser", return_5d=-2.6, return_1d=-1.0,
                    direction="supports ↓", sector="Rates"),
            _ticker("TBT", "beneficiary", return_5d=5.1, return_1d=2.0,
                    sector="Rates"),
        ],
    ),
]


PERSISTENT_SEEDS = [
    dict(
        headline="US LNG export approvals accelerate vs European demand",
        timestamp_hours_ago=240.0,
        event_date_days_ago=10,
        mechanism_summary=(
            "Sustained European LNG demand + accelerating US export "
            "permits drive multi-month repricing of LNG infrastructure, "
            "midstream operators, and natural gas producers."
        ),
        mechanism_family="commodity_squeeze",
        transmission_chain=[
            "EU LNG demand persistent",
            "US export capacity expanding",
            "Midstream + gas producers benefit",
            "Repricing held past initial gap",
        ],
        transmission_path=["LNG", "AMLP", "UNG"],
        beneficiaries=["LNG", "AMLP", "UNG"],
        losers=[],
        market_tickers=[
            _ticker("LNG", "beneficiary", return_5d=6.2, return_1d=1.5,
                    sector="Energy"),
            _ticker("AMLP", "beneficiary", return_5d=4.4, return_1d=0.9,
                    sector="Energy"),
            _ticker("UNG", "beneficiary", return_5d=5.3, return_1d=1.2,
                    sector="Energy"),
        ],
        persistence_signal_state="gap_and_hold",
        minimum_proof_set=_proof_set(["LNG", "AMLP", "UNG"]),
        key_falsifiers=_falsifier_set(["LNG", "AMLP", "UNG"]),
    ),
    dict(
        headline="India infrastructure CapEx cycle confirmed by budget",
        timestamp_hours_ago=336.0,
        event_date_days_ago=14,
        mechanism_summary=(
            "Multi-year infrastructure CapEx from India's budget keeps "
            "Indian industrials, cement, and bank credit demand bid; "
            "India equity ETFs reprice on growth durability."
        ),
        mechanism_family="fiscal_capex",
        transmission_chain=[
            "Budget CapEx confirmed",
            "Industrials + cement order books fill",
            "Bank credit demand sustained",
            "EM-India ETFs reprice on durability",
        ],
        transmission_path=["INDA", "EPI", "SMIN"],
        beneficiaries=["INDA", "EPI", "SMIN"],
        losers=[],
        market_tickers=[
            _ticker("INDA", "beneficiary", return_5d=4.8, return_1d=0.8,
                    sector="EM"),
            _ticker("EPI", "beneficiary", return_5d=5.5, return_1d=1.0,
                    sector="EM"),
            _ticker("SMIN", "beneficiary", return_5d=6.7, return_1d=1.4,
                    sector="EM"),
        ],
        persistence_signal_state="grind",
        minimum_proof_set=_proof_set(["INDA", "EPI", "SMIN"]),
        key_falsifiers=_falsifier_set(["INDA", "EPI", "SMIN"]),
    ),
    dict(
        headline="Global defence spending uplift confirmed by NATO",
        timestamp_hours_ago=504.0,
        event_date_days_ago=21,
        mechanism_summary=(
            "Sustained NATO defence spending uplift continues to "
            "support primes' multi-year backlog growth, with "
            "second-leg repricing as additional contracts confirm."
        ),
        mechanism_family="fiscal_capex",
        transmission_chain=[
            "NATO uplift reaffirmed",
            "Primes' backlog visibility extends",
            "Second-leg repricing across the cohort",
        ],
        transmission_path=["ITA", "PPA", "LMT"],
        beneficiaries=["ITA", "PPA", "LMT"],
        losers=[],
        market_tickers=[
            _ticker("ITA", "beneficiary", return_5d=5.1, return_1d=0.6,
                    sector="Industrials"),
            _ticker("PPA", "beneficiary", return_5d=4.9, return_1d=0.5,
                    sector="Industrials"),
            _ticker("LMT", "beneficiary", return_5d=6.3, return_1d=0.7,
                    sector="Industrials"),
        ],
        persistence_signal_state="second_leg",
        minimum_proof_set=_proof_set(["ITA", "PPA", "LMT"]),
        key_falsifiers=_falsifier_set(["ITA", "PPA", "LMT"]),
    ),
]


# ---------------------------------------------------------------------------
# Insert / clear / verify
# ---------------------------------------------------------------------------

def _all_seeds() -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    for spec in TODAY_SEEDS:
        rows.append(("today", _seed_event(**spec)))
    for spec in WEEKLY_SEEDS:
        rows.append(("weekly", _seed_event(**spec)))
    for spec in PERSISTENT_SEEDS:
        rows.append(("persistent", _seed_event(**spec)))
    return rows


def _print_banner() -> None:
    print("=" * 72)
    print("Second Order — showcase / demo seed")
    print("=" * 72)
    print(f"DB file               : {db.DB_FILE}")
    print(f"Demo headline prefix  : {DEMO_HEADLINE_PREFIX!r}")
    print(f"Demo model tag        : {DEMO_MODEL_TAG!r}")
    print("Demo rows are CLEARLY MARKED.  They are inserted into the "
          "live SQLite archive and will appear on the local UI alongside "
          "real events until removed via --clear.")
    print("-" * 72)


def clear_demo_rows() -> int:
    """Delete every row whose ``model`` matches the demo tag.

    Returns the row count actually deleted.  A late ``movers_cache``
    invalidate keeps the cached mover slices in sync.
    """
    if not os.path.exists(db.DB_FILE):
        print(f"[seed] no DB at {db.DB_FILE} — nothing to clear")
        return 0
    with db.connect_db() as conn:
        cur = conn.execute(
            "DELETE FROM events WHERE model = ?", (DEMO_MODEL_TAG,),
        )
        deleted = cur.rowcount
    try:
        import movers_cache
        movers_cache.invalidate()
    except Exception:
        pass
    try:
        import api as _api
        _api._TODAYS_MOVERS_CACHE["data"] = None
    except Exception:
        pass
    print(f"[seed] cleared {deleted} demo row(s) "
          f"(model = {DEMO_MODEL_TAG!r})")
    return deleted


def insert_demo_rows(*, dry_run: bool) -> list[tuple[str, str]]:
    """Insert every seed.  Returns ``[(window, headline), …]`` for the
    rows that were inserted.  ``dry_run`` skips the writes but still
    returns the planned set so the caller can audit it.
    """
    if not dry_run:
        db.init_db()
    inserted: list[tuple[str, str]] = []
    for window, event in _all_seeds():
        if dry_run:
            print(f"[seed] DRY-RUN would insert "
                  f"({window}) {event['headline']}")
        else:
            db.save_event(event)
            print(f"[seed] inserted ({window}) {event['headline']}")
        inserted.append((window, event["headline"]))
    if not dry_run:
        try:
            import movers_cache
            movers_cache.invalidate()
        except Exception:
            pass
        try:
            import api as _api
            _api._TODAYS_MOVERS_CACHE["data"] = None
        except Exception:
            pass
    return inserted


def verify_against_endpoints() -> None:
    """Hit the local mover endpoints (in-process TestClient — no
    network) and report which DEMO headlines surfaced where.

    The script does not loosen any production gate.  A demo row that
    fails the live persistent high-impact rule will simply not appear
    on the persistent surface, and this report will say so explicitly.
    """
    try:
        from fastapi.testclient import TestClient
        import api as _api
    except Exception as exc:  # pragma: no cover — import-time only
        print(f"[seed] verification skipped (TestClient unavailable: {exc})")
        return
    client = TestClient(_api.app)

    def _items(body) -> list:
        if isinstance(body, dict) and "items" in body:
            return body["items"]
        return body if isinstance(body, list) else []

    def _hits(path: str) -> list[str]:
        try:
            r = client.get(path)
        except Exception as exc:
            print(f"[seed] {path} request failed: {exc}")
            return []
        if r.status_code != 200:
            print(f"[seed] {path} returned {r.status_code}")
            return []
        return [
            m["headline"] for m in _items(r.json())
            if isinstance(m, dict) and isinstance(m.get("headline"), str)
            and m["headline"].startswith(DEMO_HEADLINE_PREFIX)
        ]

    print("-" * 72)
    print("Verification — DEMO headlines on each mover surface:")
    for path, label in (
        ("/movers/today?limit=50",      "Today"),
        ("/movers/weekly?limit=50",     "Weekly"),
        ("/movers/persistent?limit=50", "Persistent (Still Moving Markets)"),
    ):
        hits = _hits(path)
        if hits:
            print(f"  {label} ({len(hits)}):")
            for h in hits:
                print(f"    - {h}")
        else:
            print(f"  {label}: no DEMO headlines surfaced")
    print("-" * 72)
    print("Note: Persistent uses a strict high-impact gate "
          "(is_high_conviction_persistent).  Any DEMO row missing "
          "from that surface failed the live rule — by design, the "
          "seed script never loosens it.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Seed local showcase events.")
    p.add_argument(
        "--clear", action="store_true",
        help="Delete all rows where model = 'showcase_seed_v1' and exit.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print the planned inserts without writing to the DB.",
    )
    p.add_argument(
        "--no-verify", action="store_true",
        help="Skip the post-insert verification against /movers/* endpoints.",
    )
    args = p.parse_args(argv)

    _print_banner()

    if args.clear:
        clear_demo_rows()
        return 0

    insert_demo_rows(dry_run=args.dry_run)
    if not args.dry_run and not args.no_verify:
        verify_against_endpoints()
    return 0


if __name__ == "__main__":
    sys.exit(main())
