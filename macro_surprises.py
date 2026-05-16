"""Persistent storage for major macro releases and central-bank events.

What it stores
--------------
One row per scheduled macro print (CPI, NFP, FOMC, ECB, ...).  Each row
carries the consensus ``expected`` value, the published ``realized``
value, and three normalised surprise fields computed at insert time:

    * ``surprise``           — ``realized − expected`` (raw units)
    * ``surprise_zscore``    — z-score of this surprise against the
      historical distribution of surprises for the same ``series``
    * ``surprise_direction`` — closed enum: ``hawkish`` | ``dovish``
      | ``up`` | ``down`` | ``inline``
    * ``surprise_magnitude`` — closed enum: ``inline`` | ``small``
      | ``moderate`` | ``large``

Direction convention is set per ``category``:

    * ``inflation`` / ``employment`` / ``growth`` / ``monetary_policy``
      → realized > expected is *hawkish* (tightening implied);
      realized < expected is *dovish*.
    * ``sentiment`` / ``trade`` / ``housing`` → realized > expected is
      *up*; realized < expected is *down*.

For rate-decision series (``us_fomc_rate``, ``ecb_rate``, ...)
``expected`` is the consensus point estimate for the target rate, not
the market-implied probability of a hike.  Surprises of 25 bp on a
policy rate vs 0.2 pp on CPI live in the same ``surprise`` column; the
z-score normalisation handles the unit mismatch downstream.

Design constraints
------------------
* Natural dedup key is ``UNIQUE(series, release_time)``.  ``release_id``
  is a convenience string callers may supply but is not the primary
  dedup lever.
* Surprise stats (zscore / direction / magnitude) are **frozen at
  insert time** against the priors that exist at that moment.  Later
  inserts do not retroactively rewrite older rows — this matches the
  frozen-archive pattern used elsewhere and keeps older research
  reproducible.
* Thin-history floor: with fewer than ``_MIN_PRIOR_SURPRISES`` priors
  for a series we emit ``surprise_zscore=None`` and
  ``surprise_magnitude=None`` rather than a noise-driven "large".
* ``compute_surprise`` is pure — no DB access.  The upsert wrapper
  fetches priors from SQLite and hands them to the classifier.
* No ingestion / scheduler here.  The upsert API is the seam a future
  data feed plugs into.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

import db as _db

DB_FILE = _db.DB_FILE


# ---------------------------------------------------------------------------
# Closed enums.  ``SERIES_CATEGORY`` also acts as the allow-list for
# ``series`` — an upsert with an unknown series raises ``ValueError``
# rather than silently creating a one-off row that can't be compared
# against anything.
# ---------------------------------------------------------------------------

CATEGORY_IDS: tuple[str, ...] = (
    "inflation",
    "employment",
    "growth",
    "monetary_policy",
    "sentiment",
    "trade",
    "housing",
)

DIRECTION_IDS: tuple[str, ...] = (
    "hawkish",
    "dovish",
    "up",
    "down",
    "inline",
)

MAGNITUDE_IDS: tuple[str, ...] = (
    "inline",
    "small",
    "moderate",
    "large",
)

SERIES_CATEGORY: dict[str, str] = {
    # Inflation — US + major non-US CPI / PPI / deflator prints.
    "us_cpi_yoy":                 "inflation",
    "us_core_cpi_yoy":            "inflation",
    "us_cpi_mom":                 "inflation",
    "us_core_cpi_mom":            "inflation",
    "us_ppi_yoy":                 "inflation",
    "us_pce_yoy":                 "inflation",
    "us_core_pce_yoy":            "inflation",
    "eu_cpi_yoy":                 "inflation",
    "eu_core_cpi_yoy":            "inflation",
    "uk_cpi_yoy":                 "inflation",
    "uk_core_cpi_yoy":            "inflation",
    "jp_cpi_yoy":                 "inflation",
    "cn_cpi_yoy":                 "inflation",
    "in_cpi_yoy":                 "inflation",
    "br_cpi_yoy":                 "inflation",
    "mx_cpi_yoy":                 "inflation",
    # Employment
    "us_nfp":                     "employment",
    "us_unemployment_rate":       "employment",
    "us_avg_hourly_earnings_yoy": "employment",
    "us_initial_jobless_claims":  "employment",
    "eu_unemployment_rate":       "employment",
    "uk_unemployment_rate":       "employment",
    "jp_unemployment_rate":       "employment",
    # Growth — GDP / PMI / industrial production across regions.
    "us_gdp_qoq":                 "growth",
    "eu_gdp_qoq":                 "growth",
    "uk_gdp_qoq":                 "growth",
    "jp_gdp_qoq":                 "growth",
    "cn_gdp_yoy":                 "growth",
    "us_ism_manufacturing":       "growth",
    "us_ism_services":            "growth",
    "us_retail_sales_mom":        "growth",
    "eu_pmi_manufacturing":       "growth",
    "eu_pmi_services":            "growth",
    "uk_pmi_manufacturing":       "growth",
    "cn_pmi_manufacturing":       "growth",
    "cn_industrial_production_yoy": "growth",
    "eu_industrial_production_mom": "growth",
    # Monetary policy — rate-decision point estimates across central banks.
    "us_fomc_rate":               "monetary_policy",
    "ecb_rate":                   "monetary_policy",
    "boe_rate":                   "monetary_policy",
    "boj_rate":                   "monetary_policy",
    "pboc_lpr":                   "monetary_policy",
    "boc_rate":                   "monetary_policy",   # Bank of Canada
    "rba_rate":                   "monetary_policy",   # Reserve Bank of Australia
    "rbi_rate":                   "monetary_policy",   # Reserve Bank of India
    "snb_rate":                   "monetary_policy",   # Swiss National Bank
    "br_selic":                   "monetary_policy",   # Brazil Selic
    "mx_tiie":                    "monetary_policy",   # Mexico overnight target
    # Sentiment
    "us_consumer_confidence":     "sentiment",
    "us_umich_sentiment":         "sentiment",
    "eu_economic_sentiment":      "sentiment",
    "de_ifo":                     "sentiment",         # German IFO business climate
    # Trade
    "us_trade_balance":           "trade",
    "eu_trade_balance":           "trade",
    "cn_trade_balance":           "trade",
    "jp_trade_balance":           "trade",
    # Housing — thinner globally; US only for now.
    "us_housing_starts":          "housing",
    "us_existing_home_sales":     "housing",
}

SERIES_IDS: tuple[str, ...] = tuple(sorted(SERIES_CATEGORY.keys()))


# Which direction is "hawkish" vs "up" for each category.  A higher
# realized value than expected pushes in the listed direction; a lower
# value flips it.  ``hawkish_if_higher`` maps to the hawkish/dovish
# axis; ``up_if_higher`` maps to the up/down axis.
_CATEGORY_DIRECTION: dict[str, str] = {
    "inflation":       "hawkish_if_higher",
    "employment":      "hawkish_if_higher",
    "growth":          "hawkish_if_higher",
    "monetary_policy": "hawkish_if_higher",
    "sentiment":       "up_if_higher",
    "trade":           "up_if_higher",
    "housing":         "up_if_higher",
}

# Thin-history floor.  Below this count we emit None for zscore and
# magnitude rather than classify on noise.
_MIN_PRIOR_SURPRISES: int = 5

# Absolute-z magnitude thresholds.  Picked to match the existing
# calibration sensibility (|z|<0.5 is "in the noise"; |z|>2 is tail).
_MAG_SMALL_MAX:    float = 0.5
_MAG_MODERATE_MAX: float = 1.0
_MAG_LARGE_MAX:    float = 2.0

# Raw-surprise "inline" band.  If a surprise is exactly zero — or its
# absolute value is smaller than this fraction of the expected value —
# we call the direction "inline" regardless of sign.  Protects against
# spurious "hawkish" reads on a 0.01 pp miss.
_INLINE_RELATIVE_BAND: float = 0.05


# ---------------------------------------------------------------------------
# Pure classifier.  No DB access — caller supplies the list of prior
# surprise values for this series (newest-first or oldest-first, order
# does not matter).
# ---------------------------------------------------------------------------

def compute_surprise(
    *,
    expected: Optional[float],
    realized: Optional[float],
    category: str,
    prior_surprises: list[float],
) -> dict[str, Any]:
    """Return the derived surprise block for a (expected, realized) pair.

    Returns a dict with keys ``surprise``, ``surprise_zscore``,
    ``surprise_direction``, ``surprise_magnitude``, and
    ``prior_sample_size``.  Any of ``surprise`` / ``zscore`` /
    ``magnitude`` can be ``None`` — see module docstring for rules.

    Never raises on missing inputs — if ``expected`` or ``realized`` is
    ``None`` the whole block is ``None``-filled.  Unknown ``category``
    does raise, since that's a programming error.
    """
    if category not in _CATEGORY_DIRECTION:
        raise ValueError(
            f"unknown category={category!r}; "
            f"allowed: {sorted(CATEGORY_IDS)}"
        )

    if expected is None or realized is None:
        return {
            "surprise":           None,
            "surprise_zscore":    None,
            "surprise_direction": None,
            "surprise_magnitude": None,
            "prior_sample_size":  len(prior_surprises),
        }

    surprise = float(realized) - float(expected)

    # "Inline" band: either a zero surprise or |surprise| < 5 % of |expected|.
    exp_mag = abs(float(expected))
    inline_floor = _INLINE_RELATIVE_BAND * exp_mag if exp_mag > 0 else 0.0
    is_inline_raw = abs(surprise) <= inline_floor

    direction: Optional[str]
    convention = _CATEGORY_DIRECTION[category]
    if is_inline_raw:
        direction = "inline"
    elif convention == "hawkish_if_higher":
        direction = "hawkish" if surprise > 0 else "dovish"
    else:
        direction = "up" if surprise > 0 else "down"

    # Z-score + magnitude.  Thin-history floor applies: without enough
    # priors we refuse to classify magnitude.
    priors = [float(x) for x in prior_surprises if x is not None]
    n_prior = len(priors)
    zscore: Optional[float] = None
    magnitude: Optional[str] = None

    if n_prior >= _MIN_PRIOR_SURPRISES:
        mean = sum(priors) / n_prior
        var = sum((p - mean) ** 2 for p in priors) / n_prior
        std = math.sqrt(var)
        if std > 0:
            zscore = (surprise - mean) / std
            zabs = abs(zscore)
            if is_inline_raw:
                magnitude = "inline"
            elif zabs < _MAG_SMALL_MAX:
                magnitude = "inline"
            elif zabs < _MAG_MODERATE_MAX:
                magnitude = "small"
            elif zabs < _MAG_LARGE_MAX:
                magnitude = "moderate"
            else:
                magnitude = "large"
        else:
            # All priors identical.  Any nonzero surprise is unprecedented.
            zscore = 0.0 if surprise == 0.0 else float("inf")
            magnitude = "inline" if surprise == 0.0 else "large"

    return {
        "surprise":           surprise,
        "surprise_zscore":    zscore,
        "surprise_direction": direction,
        "surprise_magnitude": magnitude,
        "prior_sample_size":  n_prior,
    }


# ---------------------------------------------------------------------------
# CRUD.  The upsert API is the seam a future data feed plugs into.
# ---------------------------------------------------------------------------

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_release(row: tuple) -> dict[str, Any]:
    return {
        "id":                 row[0],
        "release_id":         row[1],
        "series":             row[2],
        "category":           row[3],
        "country":            row[4],
        "release_time":       row[5],
        "expected":           row[6],
        "realized":           row[7],
        "unit":               row[8],
        "surprise":           row[9],
        "surprise_zscore":    row[10],
        "surprise_direction": row[11],
        "surprise_magnitude": row[12],
        "prior_sample_size":  row[13],
        "notes":              row[14],
        "created_at":         row[15],
        "updated_at":         row[16],
    }


_SELECT_COLUMNS = (
    "id, release_id, series, category, country, release_time, "
    "expected, realized, unit, surprise, surprise_zscore, "
    "surprise_direction, surprise_magnitude, prior_sample_size, "
    "notes, created_at, updated_at"
)


def _get_prior_surprises(
    conn: sqlite3.Connection, series: str, release_time: str,
) -> list[float]:
    """Return every prior, non-null surprise for this series.

    "Prior" = strictly before ``release_time``.  A re-upsert of the
    same release does not count itself as a prior.
    """
    rows = conn.execute(
        "SELECT surprise FROM macro_releases "
        "WHERE series = ? AND release_time < ? AND surprise IS NOT NULL",
        (series, release_time),
    ).fetchall()
    return [r[0] for r in rows]


def upsert_release(
    *,
    series: str,
    release_time: str,
    expected: Optional[float] = None,
    realized: Optional[float] = None,
    unit: str = "",
    country: str = "",
    release_id: Optional[str] = None,
    notes: str = "",
) -> dict[str, Any]:
    """Insert or update a macro release row.

    Dedups on ``(series, release_time)``.  Recomputes the surprise block
    against the priors that exist at call time and stores the result.

    Raises ``ValueError`` on unknown ``series`` or ill-formed inputs.
    """
    if series not in SERIES_CATEGORY:
        raise ValueError(
            f"unknown series={series!r}; add it to SERIES_CATEGORY "
            f"or use one of {sorted(SERIES_IDS)[:5]}..."
        )
    if not isinstance(release_time, str) or not release_time.strip():
        raise ValueError("release_time must be a non-empty ISO-8601 string")
    release_time = release_time.strip()
    try:
        # Tolerate trailing 'Z'.
        datetime.fromisoformat(release_time.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"release_time={release_time!r} is not a valid ISO-8601 timestamp"
        ) from exc

    for num, label in ((expected, "expected"), (realized, "realized")):
        if num is not None and not isinstance(num, (int, float)):
            raise ValueError(f"{label} must be a number or None")
        if isinstance(num, bool):
            raise ValueError(f"{label} must be a number, not a bool")
        if num is not None and not math.isfinite(float(num)):
            raise ValueError(f"{label} must be finite; got {num!r}")

    category = SERIES_CATEGORY[series]
    now = _utcnow_iso()

    with _db.connect_db() as conn:
        priors = _get_prior_surprises(conn, series, release_time)
        block = compute_surprise(
            expected=expected,
            realized=realized,
            category=category,
            prior_surprises=priors,
        )

        existing = conn.execute(
            "SELECT id, created_at FROM macro_releases "
            "WHERE series = ? AND release_time = ?",
            (series, release_time),
        ).fetchone()

        if existing is None:
            cur = conn.execute(
                "INSERT INTO macro_releases "
                "(release_id, series, category, country, release_time, "
                " expected, realized, unit, surprise, surprise_zscore, "
                " surprise_direction, surprise_magnitude, "
                " prior_sample_size, notes, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    release_id, series, category, country, release_time,
                    expected, realized, unit,
                    block["surprise"], block["surprise_zscore"],
                    block["surprise_direction"], block["surprise_magnitude"],
                    block["prior_sample_size"], notes, now, now,
                ),
            )
            row_id = cur.lastrowid
        else:
            row_id = existing[0]
            conn.execute(
                "UPDATE macro_releases SET "
                "release_id = ?, category = ?, country = ?, "
                "expected = ?, realized = ?, unit = ?, "
                "surprise = ?, surprise_zscore = ?, "
                "surprise_direction = ?, surprise_magnitude = ?, "
                "prior_sample_size = ?, notes = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    release_id, category, country,
                    expected, realized, unit,
                    block["surprise"], block["surprise_zscore"],
                    block["surprise_direction"], block["surprise_magnitude"],
                    block["prior_sample_size"], notes, now, row_id,
                ),
            )

    result = get_release(row_id)
    assert result is not None  # just wrote it
    return result


def get_release(row_id: int) -> Optional[dict[str, Any]]:
    """Load a single release by primary key."""
    if not isinstance(row_id, int) or isinstance(row_id, bool):
        raise ValueError("row_id must be an int")
    with _db.connect_db() as conn:
        row = conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM macro_releases WHERE id = ?",
            (row_id,),
        ).fetchone()
    return _row_to_release(row) if row else None


def get_release_by_key(
    series: str, release_time: str,
) -> Optional[dict[str, Any]]:
    """Load a release by its natural key ``(series, release_time)``."""
    with _db.connect_db() as conn:
        row = conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM macro_releases "
            f"WHERE series = ? AND release_time = ?",
            (series, release_time),
        ).fetchone()
    return _row_to_release(row) if row else None


def list_releases(
    *,
    series: Optional[str] = None,
    category: Optional[str] = None,
    country: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """List macro releases, newest first.  All filters are optional."""
    if limit < 1 or limit > 5000:
        raise ValueError("limit must be in [1, 5000]")
    if series is not None and series not in SERIES_CATEGORY:
        raise ValueError(f"unknown series={series!r}")
    if category is not None and category not in _CATEGORY_DIRECTION:
        raise ValueError(f"unknown category={category!r}")

    clauses: list[str] = []
    params: list[Any] = []
    if series is not None:
        clauses.append("series = ?")
        params.append(series)
    if category is not None:
        clauses.append("category = ?")
        params.append(category)
    if country is not None:
        clauses.append("country = ?")
        params.append(country)
    if since is not None:
        clauses.append("release_time >= ?")
        params.append(since)
    if until is not None:
        clauses.append("release_time <= ?")
        params.append(until)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with _db.connect_db() as conn:
        rows = conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM macro_releases {where} "
            f"ORDER BY release_time DESC, id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [_row_to_release(r) for r in rows]


def delete_release(row_id: int) -> bool:
    """Delete by id.  Returns True when a row was removed."""
    if not isinstance(row_id, int) or isinstance(row_id, bool):
        raise ValueError("row_id must be an int")
    with _db.connect_db() as conn:
        # Null out the pointer on any events that referenced this row so
        # we don't leave dangling FKs.
        conn.execute(
            "UPDATE events SET macro_release_id = NULL "
            "WHERE macro_release_id = ?",
            (row_id,),
        )
        cur = conn.execute(
            "DELETE FROM macro_releases WHERE id = ?", (row_id,)
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Event linkage — one-way FK on the ``events`` side.  A news event can
# point to at most one macro release; multiple events may share a
# release, which covers the common "CPI drop → 6 reaction headlines"
# case without needing a join table.
# ---------------------------------------------------------------------------

def link_event_to_release(event_id: int, release_id: int) -> None:
    """Attach ``events.macro_release_id = release_id`` on one event.

    Raises ``ValueError`` if either row doesn't exist.
    """
    if not isinstance(event_id, int) or isinstance(event_id, bool):
        raise ValueError("event_id must be an int")
    if not isinstance(release_id, int) or isinstance(release_id, bool):
        raise ValueError("release_id must be an int")
    with _db.connect_db() as conn:
        exists_release = conn.execute(
            "SELECT 1 FROM macro_releases WHERE id = ?", (release_id,)
        ).fetchone()
        if exists_release is None:
            raise ValueError(f"macro release {release_id} not found")
        exists_event = conn.execute(
            "SELECT 1 FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if exists_event is None:
            raise ValueError(f"event {event_id} not found")
        conn.execute(
            "UPDATE events SET macro_release_id = ? WHERE id = ?",
            (release_id, event_id),
        )


def unlink_event(event_id: int) -> None:
    """Clear the macro_release_id pointer on one event."""
    if not isinstance(event_id, int) or isinstance(event_id, bool):
        raise ValueError("event_id must be an int")
    with _db.connect_db() as conn:
        conn.execute(
            "UPDATE events SET macro_release_id = NULL WHERE id = ?",
            (event_id,),
        )


def list_events_for_release(release_id: int) -> list[int]:
    """Return every event_id that points at the given release."""
    if not isinstance(release_id, int) or isinstance(release_id, bool):
        raise ValueError("release_id must be an int")
    with _db.connect_db() as conn:
        rows = conn.execute(
            "SELECT id FROM events WHERE macro_release_id = ? ORDER BY id",
            (release_id,),
        ).fetchall()
    return [r[0] for r in rows]
