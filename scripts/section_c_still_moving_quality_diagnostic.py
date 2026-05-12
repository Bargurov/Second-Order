#!/usr/bin/env python3
"""Section-C Still Moving Market candidate quality diagnostic.

Read-only diagnostic that scans curated Still Moving Market
candidates and flags rows that are weak along any of five known
axes:

  * noisy / missing / mis-chosen ticker
    (``weak_ticker`` / ``bad_proxy``)
  * missing ``price_cache`` coverage on the primary OR benchmark
    (``missing_price_cache``)
  * no benchmark-adjusted evidence on file for the event
    (``no_benchmark_adjusted_evidence``)
  * no persistence signal recorded for the event
    (``no_persistence_signal``)
  * duplicate narrative across two or more candidates
    (``duplicate_narrative``)

The diagnostic does NOT change the shipped still-moving logic, does
NOT decide which candidate ships, and does NOT mutate the archive,
``price_cache``, or any artifact under ``artifacts/``.  It is a
*report*: an operator reads it to see which candidates would survive
each filter and which would fall out, and chooses whether to wire
any of the recommended filter rules into the surface.

Read-only by construction
-------------------------

* Only ``SELECT`` against ``price_cache`` via a single patchable
  seam.  No INSERT / UPDATE / DELETE.
* Reads ``artifacts/freeze_candidate_evidence.json`` and an
  optional persistence-signal JSON via patchable seams.  Missing
  files degrade to "no evidence on file" / "no signal on file" —
  never to an exception.
* No provider call (no ``yfinance`` / ``market_data`` / paid path),
  no LLM, no FastAPI surface (never imports ``api`` /
  ``routes.*``).  The diagnostic also does NOT import the shipped
  still-moving modules (``movers_ranking``, ``persistence_signal``)
  so it cannot accidentally pull a side-effect from them.
* ``--output`` is the only filesystem side effect, and only when
  explicitly passed.

Output contract (JSON)::

    {
      "ok":                       bool,
      "candidates_checked":       int,
      "defensible_candidates":    int,
      "weak_ticker_cases":        int,
      "bad_proxy_cases":          int,
      "missing_price_cache_cases":int,
      "no_persistence_cases":     int,
      "duplicate_narrative_cases":int,
      "recommended_still_moving_filter_rules": [str, ...],
      "warnings":                 [str, ...],
      "errors":                   [str, ...],
      "candidates": [
        {
          "event_id":                              int | None,
          "headline":                              str | None,
          "event_date":                            str | None,
          "primary_ticker":                        str | None,
          "benchmark_ticker":                      str | None,
          "mechanism_family":                      str | None,
          "ticker_quality":                        str,
          "price_cache_available":                 bool,
          "benchmark_adjusted_evidence_available": bool,
          "persistence_signal":                    str | None,
          "diagnostic_tags":                       [str, ...],
          "inclusion_reason":                      str,
          "exclusion_reason":                      str,
        },
        ...
      ]
    }

The 11 spec keys are the audit envelope; ``candidates`` is the
per-row detail an operator inspects when a count looks off.  Both
``inclusion_reason`` and ``exclusion_reason`` are always present on
every row — exactly one carries text, the other is the empty
string.

``bad_proxy`` is a strict subset of ``weak_ticker``: a candidate
whose primary equals its benchmark, OR whose primary is a known
sector ETF, increments BOTH counters.  Reading "12 weak + 5
bad_proxy" as "17 problems" double-counts; the right reading is "12
weak, of which 5 are the more specific bad-proxy choice."

Conservative wording — the diagnostic surfaces shape, never a
verdict.  Banned tokens in any text the diagnostic emits (the
``recommended_still_moving_filter_rules`` list, ``warnings``,
``errors``, ``inclusion_reason``, ``exclusion_reason``):
``proof``, ``proves``, ``proven``, ``alpha``, ``guaranteed``,
``automatically``, ``automatic``, ``validated``, ``definitely``,
``causes``, ``causation``, ``correct ticker``.  The diagnostic never
claims a candidate is the right call — it claims it is *defensible*
against the listed weakness axes.

Usage::

    python scripts/section_c_still_moving_quality_diagnostic.py --json
    python scripts/section_c_still_moving_quality_diagnostic.py --json \\
        --yaml-path examples/curated_events.example.yaml
    python scripts/section_c_still_moving_quality_diagnostic.py --json \\
        --output artifacts/section_c_still_moving_quality.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_YAML_PATH:                str = "examples/curated_events.example.yaml"
_DEFAULT_EVIDENCE_ARTIFACT_PATH:   str = (
    "artifacts/freeze_candidate_evidence.json"
)
_DEFAULT_PERSISTENCE_SIGNALS_PATH: str | None = None

# Sector ETFs that should not show up as a candidate's PRIMARY
# ticker — the primary should be a single name; sector ETFs belong
# on the benchmark side of the row.  The list is deliberately small
# and conservative; tests pin the canonical entries.
_SECTOR_ETFS_AS_PRIMARY_BLOCKLIST: frozenset[str] = frozenset({
    "SPY",
    "XLE", "XLF", "XLK", "XLV", "XLI", "XLB",
    "XLU", "XLY", "XLP", "XLRE",
    "SMH", "XAR",
})


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _load_candidates(
    yaml_path: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Wrap :func:`scripts.curated_event_loader.load_curated_events`.

    Lazy import keeps the loader's YAML cost off the un-patched test
    path.  Returns the loader's ``(events, errors)`` tuple unchanged.
    """
    from scripts.curated_event_loader import load_curated_events

    return load_curated_events(yaml_path)


def _load_cache_summaries(
    *,
    db_path: str | None,
    tickers: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Issue ``SELECT COUNT(*), MIN(date), MAX(date) FROM price_cache
    WHERE UPPER(ticker) = ?`` once per distinct ticker.

    Returns a mapping ``ticker_upper -> {rows_in_cache, min_date,
    max_date}``.  Tickers absent from the cache surface as a row of
    zeros so callers can render them without a special case.

    Read-only by construction.
    """
    cleaned = sorted({
        t.strip().upper() for t in tickers
        if isinstance(t, str) and t.strip()
    })
    out: dict[str, dict[str, Any]] = {
        t: {"rows_in_cache": 0, "min_date": None, "max_date": None}
        for t in cleaned
    }
    if not cleaned:
        return out

    path = _resolve_db_path(db_path)
    if path is None or not Path(path).exists():
        return out

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return out

    try:
        for ticker in cleaned:
            try:
                row = conn.execute(
                    "SELECT COUNT(*), MIN(date), MAX(date) "
                    "FROM price_cache "
                    "WHERE UPPER(ticker) = ? "
                    "AND date IS NOT NULL AND date != ''",
                    (ticker,),
                ).fetchone()
            except sqlite3.Error:
                row = None
            if not row:
                continue
            count, min_d, max_d = row
            out[ticker] = {
                "rows_in_cache": int(count) if isinstance(count, int) else 0,
                "min_date":      min_d if isinstance(min_d, str) and min_d else None,
                "max_date":      max_d if isinstance(max_d, str) and max_d else None,
            }
    finally:
        conn.close()

    return out


def _load_benchmark_adjusted_evidence(
    *,
    artifact_path: str | None,
) -> set[int]:
    """Open the freeze-candidate evidence artifact and collect the
    set of ``event_id``s that carry a benchmark-adjusted record (a
    record whose ``benchmark`` field is a non-blank string).

    Missing or malformed artifacts degrade to ``set()`` — the
    diagnostic surfaces the gap as a tag, not a crash.
    """
    if not artifact_path:
        return set()
    p = Path(artifact_path)
    if not p.exists():
        return set()
    try:
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, dict):
        return set()
    out: set[int] = set()
    for rec in data.get("records") or []:
        if not isinstance(rec, dict):
            continue
        ev_id = rec.get("event_id")
        bench = rec.get("benchmark")
        if not isinstance(ev_id, int):
            continue
        if isinstance(bench, str) and bench.strip():
            out.add(ev_id)
    return out


def _load_persistence_signals(
    *,
    signals_path: str | None,
) -> dict[int, str]:
    """Load an optional ``event_id -> signal_label`` JSON mapping.

    Expected shape: either a flat dict ``{"<event_id>":
    "<signal>"}`` or a list of ``{"event_id": int, "signal": str}``
    objects.  Anything else degrades to ``{}``.
    """
    if not signals_path:
        return {}
    p = Path(signals_path)
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[int, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                ev_id = int(k)
            except (TypeError, ValueError):
                continue
            if isinstance(v, str) and v.strip():
                out[ev_id] = v.strip()
    elif isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            ev_id = entry.get("event_id")
            sig = entry.get("signal")
            if isinstance(ev_id, int) and isinstance(sig, str) and sig.strip():
                out[ev_id] = sig.strip()
    return out


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:  # noqa: BLE001 — best-effort default
        return None
    return getattr(_db, "DB_FILE", None)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_section_c_still_moving_quality_diagnostic(
    *,
    yaml_path:              str | None = _DEFAULT_YAML_PATH,
    db_path:                str | None = None,
    evidence_artifact_path: str | None = _DEFAULT_EVIDENCE_ARTIFACT_PATH,
    persistence_signals_path: str | None = _DEFAULT_PERSISTENCE_SIGNALS_PATH,
    output_path:            str | None = None,
) -> dict[str, Any]:
    """Run the read-only still-moving quality diagnostic.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    candidates_raw, load_errors = _safe_load_candidates(
        yaml_path=yaml_path, errors=errors,
    )
    for e in load_errors:
        if isinstance(e, str) and e:
            errors.append(e)

    # Collect every primary + benchmark ticker we will need a cache
    # summary for, then load summaries in one pass.
    summary_tickers: set[str] = set()
    for c in candidates_raw:
        if not isinstance(c, dict):
            continue
        for k in ("primary_ticker", "benchmark_ticker"):
            v = c.get(k)
            if isinstance(v, str) and v.strip():
                summary_tickers.add(v.strip().upper())

    cache_summaries = _safe_dict(_safe_load_cache_summaries(
        db_path=db_path, tickers=sorted(summary_tickers),
        errors=errors,
    ))

    evidence_set = _safe_set_of_ints(_safe_load_evidence(
        artifact_path=evidence_artifact_path, errors=errors,
    ))

    persistence_map = _safe_persistence(_safe_load_persistence(
        signals_path=persistence_signals_path, errors=errors,
    ))

    # First pass: collect normalized headlines so we can detect
    # duplicates in the second pass.
    headline_counts: dict[str, int] = {}
    for c in candidates_raw:
        if not isinstance(c, dict):
            continue
        norm = _normalize_headline(c.get("headline"))
        if norm:
            headline_counts[norm] = headline_counts.get(norm, 0) + 1

    # Second pass: build per-candidate rows.
    candidates_out: list[dict[str, Any]] = []
    for c in candidates_raw:
        if not isinstance(c, dict):
            warnings.append(
                "non-dict entry skipped in curated candidate list"
            )
            continue
        row = _diagnose_candidate(
            candidate=c,
            cache_summaries=cache_summaries,
            evidence_set=evidence_set,
            persistence_map=persistence_map,
            headline_counts=headline_counts,
        )
        candidates_out.append(row)

    # Aggregate the audit counts.
    counts = _aggregate_counts(candidates_out)
    recommended = _recommend_rules(counts)

    envelope = {
        "ok":                                    not errors,
        "candidates_checked":                    counts["candidates_checked"],
        "defensible_candidates":                 counts["defensible_candidates"],
        "weak_ticker_cases":                     counts["weak_ticker_cases"],
        "bad_proxy_cases":                       counts["bad_proxy_cases"],
        "missing_price_cache_cases":             counts["missing_price_cache_cases"],
        "no_persistence_cases":                  counts["no_persistence_cases"],
        "duplicate_narrative_cases":             counts["duplicate_narrative_cases"],
        "recommended_still_moving_filter_rules": recommended,
        "warnings":                              warnings,
        "errors":                                errors,
        "candidates":                            candidates_out,
    }
    return _finalize(envelope=envelope, output_path=output_path)


# ---------------------------------------------------------------------------
# Per-candidate compute
# ---------------------------------------------------------------------------


def _diagnose_candidate(
    *,
    candidate:       dict[str, Any],
    cache_summaries: dict[str, dict[str, Any]],
    evidence_set:    set[int],
    persistence_map: dict[int, str],
    headline_counts: dict[str, int],
) -> dict[str, Any]:
    event_id     = _coerce_int_or_none(candidate.get("event_id"))
    headline     = _coerce_str_or_none(candidate.get("headline"))
    event_date   = _coerce_event_date(candidate.get("event_date"))
    primary      = _coerce_str_or_none(candidate.get("primary_ticker"))
    benchmark    = _coerce_str_or_none(candidate.get("benchmark_ticker"))
    family       = _coerce_str_or_none(candidate.get("mechanism_family"))

    ticker_quality = _classify_ticker_quality(
        primary=primary, benchmark=benchmark,
    )

    price_cache_available = _price_cache_available(
        primary=primary, benchmark=benchmark,
        cache_summaries=cache_summaries,
    )

    benchmark_adjusted_available = (
        isinstance(event_id, int) and event_id in evidence_set
    )

    persistence_signal = None
    if isinstance(event_id, int):
        persistence_signal = persistence_map.get(event_id)

    tags = _build_tags(
        ticker_quality=ticker_quality,
        price_cache_available=price_cache_available,
        benchmark_adjusted_available=benchmark_adjusted_available,
        persistence_signal=persistence_signal,
        headline=headline,
        headline_counts=headline_counts,
    )

    if tags:
        inclusion_reason = ""
        exclusion_reason = _exclusion_reason(tags)
    else:
        inclusion_reason = (
            "Candidate is defensible against the five listed "
            "weakness axes (ticker quality, price_cache coverage, "
            "benchmark-adjusted evidence on file, persistence "
            "signal on file, narrative uniqueness).  The diagnostic "
            "reports shape only and does not endorse the candidate."
        )
        exclusion_reason = ""

    return {
        "event_id":                              event_id,
        "headline":                              headline,
        "event_date":                            event_date,
        "primary_ticker":                        primary,
        "benchmark_ticker":                      benchmark,
        "mechanism_family":                      family,
        "ticker_quality":                        ticker_quality,
        "price_cache_available":                 price_cache_available,
        "benchmark_adjusted_evidence_available": benchmark_adjusted_available,
        "persistence_signal":                    persistence_signal,
        "diagnostic_tags":                       tags,
        "inclusion_reason":                      inclusion_reason,
        "exclusion_reason":                      exclusion_reason,
    }


def _classify_ticker_quality(
    *,
    primary:   str | None,
    benchmark: str | None,
) -> str:
    if not primary:
        return "missing"
    p = primary.strip().upper()
    b = benchmark.strip().upper() if isinstance(benchmark, str) else ""
    if b and p == b:
        return "primary_equals_benchmark"
    if p in _SECTOR_ETFS_AS_PRIMARY_BLOCKLIST:
        return "sector_etf_as_primary"
    return "ok"


def _price_cache_available(
    *,
    primary:         str | None,
    benchmark:       str | None,
    cache_summaries: dict[str, dict[str, Any]],
) -> bool:
    if not primary or not benchmark:
        return False
    p_sum = cache_summaries.get(primary.strip().upper()) or {}
    b_sum = cache_summaries.get(benchmark.strip().upper()) or {}
    return (
        _safe_int(p_sum.get("rows_in_cache")) > 0
        and _safe_int(b_sum.get("rows_in_cache")) > 0
    )


def _build_tags(
    *,
    ticker_quality:                str,
    price_cache_available:         bool,
    benchmark_adjusted_available:  bool,
    persistence_signal:            str | None,
    headline:                      str | None,
    headline_counts:               dict[str, int],
) -> list[str]:
    tags: list[str] = []
    if ticker_quality != "ok":
        tags.append("weak_ticker")
        if ticker_quality in (
            "primary_equals_benchmark",
            "sector_etf_as_primary",
        ):
            tags.append("bad_proxy")
    if not price_cache_available:
        tags.append("missing_price_cache")
    if not benchmark_adjusted_available:
        tags.append("no_benchmark_adjusted_evidence")
    if not (isinstance(persistence_signal, str)
            and persistence_signal.strip()):
        tags.append("no_persistence_signal")
    norm = _normalize_headline(headline)
    if norm and headline_counts.get(norm, 0) > 1:
        tags.append("duplicate_narrative")
    # Stable, deterministic ordering.
    canonical_order = (
        "weak_ticker",
        "bad_proxy",
        "missing_price_cache",
        "no_benchmark_adjusted_evidence",
        "no_persistence_signal",
        "duplicate_narrative",
    )
    return [t for t in canonical_order if t in tags]


def _exclusion_reason(tags: list[str]) -> str:
    parts: list[str] = []
    if "weak_ticker" in tags:
        if "bad_proxy" in tags:
            parts.append(
                "ticker choice is a sector-ETF or matches the "
                "benchmark, which is a poor single-name proxy"
            )
        else:
            parts.append(
                "primary ticker is missing or unusable"
            )
    if "missing_price_cache" in tags:
        parts.append(
            "price_cache lacks rows on the primary or benchmark"
        )
    if "no_benchmark_adjusted_evidence" in tags:
        parts.append(
            "no benchmark-adjusted evidence record is on file"
        )
    if "no_persistence_signal" in tags:
        parts.append(
            "no persistence signal is on file for this event"
        )
    if "duplicate_narrative" in tags:
        parts.append(
            "headline duplicates another candidate's narrative"
        )
    body = "; ".join(parts) if parts else "weakness flagged"
    return (
        f"Diagnostic flagged {len(tags)} weakness "
        f"{'axis' if len(tags) == 1 else 'axes'}: {body}.  "
        f"The diagnostic reports shape only — an operator decides "
        f"whether to drop or keep the candidate."
    )


def _aggregate_counts(
    candidates_out: list[dict[str, Any]],
) -> dict[str, int]:
    weak_ticker = 0
    bad_proxy = 0
    missing_cache = 0
    no_persistence = 0
    duplicate = 0
    defensible = 0
    for row in candidates_out:
        tags = row.get("diagnostic_tags") or []
        if not tags:
            defensible += 1
        if "weak_ticker" in tags:
            weak_ticker += 1
        if "bad_proxy" in tags:
            bad_proxy += 1
        if "missing_price_cache" in tags:
            missing_cache += 1
        if "no_persistence_signal" in tags:
            no_persistence += 1
        if "duplicate_narrative" in tags:
            duplicate += 1
    return {
        "candidates_checked":         len(candidates_out),
        "defensible_candidates":      defensible,
        "weak_ticker_cases":          weak_ticker,
        "bad_proxy_cases":            bad_proxy,
        "missing_price_cache_cases":  missing_cache,
        "no_persistence_cases":       no_persistence,
        "duplicate_narrative_cases":  duplicate,
    }


def _recommend_rules(counts: dict[str, int]) -> list[str]:
    rules: list[str] = []
    if counts["weak_ticker_cases"] > 0:
        rules.append(
            "Filter rule: drop candidates whose ticker_quality is "
            "not 'ok' (missing primary, sector ETF as primary, or "
            "primary equals benchmark) before showing them on the "
            "Still Moving Market surface."
        )
    if counts["bad_proxy_cases"] > 0:
        rules.append(
            "Filter rule: refuse a candidate when its primary "
            "ticker is a sector ETF or matches the benchmark — "
            "this is a bad-proxy choice for a single-name read."
        )
    if counts["missing_price_cache_cases"] > 0:
        rules.append(
            "Filter rule: hide candidates that lack price_cache "
            "coverage on both the primary AND the benchmark; the "
            "surface cannot show a defensible move without both."
        )
    if counts["no_persistence_cases"] > 0:
        rules.append(
            "Filter rule: hide candidates with no persistence "
            "signal on file; 'still moving' is a persistence "
            "claim and needs a recorded signal to back it."
        )
    if counts["duplicate_narrative_cases"] > 0:
        rules.append(
            "Filter rule: dedupe candidates by normalized headline "
            "before ranking; duplicate narratives let one story "
            "occupy two slots on the surface."
        )
    return rules


# ---------------------------------------------------------------------------
# Safe seam wrappers
# ---------------------------------------------------------------------------


def _safe_load_candidates(
    *,
    yaml_path: str | None,
    errors:    list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        result = _load_candidates(yaml_path)
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"curated candidate loader raised: "
            f"{type(exc).__name__}: {exc}"
        )
        return [], []
    if not isinstance(result, tuple) or len(result) != 2:
        errors.append(
            "curated candidate loader returned an unexpected shape"
        )
        return [], []
    events, load_errors = result
    return (
        list(events) if isinstance(events, list) else [],
        list(load_errors) if isinstance(load_errors, list) else [],
    )


def _safe_load_cache_summaries(
    *,
    db_path: str | None,
    tickers: Sequence[str],
    errors:  list[str],
) -> dict[str, dict[str, Any]]:
    try:
        return _load_cache_summaries(db_path=db_path, tickers=tickers)
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"price_cache summary load raised: "
            f"{type(exc).__name__}: {exc}"
        )
        return {}


def _safe_load_evidence(
    *,
    artifact_path: str | None,
    errors:        list[str],
) -> Iterable[Any]:
    try:
        return _load_benchmark_adjusted_evidence(
            artifact_path=artifact_path,
        )
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"benchmark-adjusted evidence load raised: "
            f"{type(exc).__name__}: {exc}"
        )
        return set()


def _safe_load_persistence(
    *,
    signals_path: str | None,
    errors:       list[str],
) -> Any:
    try:
        return _load_persistence_signals(signals_path=signals_path)
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"persistence signal load raised: "
            f"{type(exc).__name__}: {exc}"
        )
        return {}


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _coerce_int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _coerce_str_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _coerce_event_date(value: Any) -> str | None:
    """Accept ISO YYYY-MM-DD strings AND ``datetime.date`` objects
    (PyYAML's native shape)."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    # datetime.date / datetime.datetime — render as ISO.
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            rendered = iso()
        except Exception:  # noqa: BLE001
            return None
        if isinstance(rendered, str):
            # ``datetime.datetime`` includes time; clip to date.
            return rendered[:10] if "T" in rendered else rendered
    return None


def _normalize_headline(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    # Collapse whitespace and lowercase so "OPEC extends cuts" and
    # "  opec EXTENDS  cuts  " hash to the same key.
    stripped = " ".join(value.split()).strip().lower()
    return stripped or None


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _safe_set_of_ints(value: Any) -> set[int]:
    if isinstance(value, set):
        return {v for v in value if isinstance(v, int)}
    if isinstance(value, (list, tuple)):
        return {v for v in value if isinstance(v, int)}
    return set()


def _safe_persistence(value: Any) -> dict[int, str]:
    if not isinstance(value, dict):
        return {}
    out: dict[int, str] = {}
    for k, v in value.items():
        if isinstance(k, int) and isinstance(v, str) and v.strip():
            out[k] = v.strip()
    return out


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------


def _finalize(
    *, envelope: dict[str, Any], output_path: str | None,
) -> dict[str, Any]:
    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(
                    envelope, fh, indent=2, sort_keys=True, default=str,
                )
        except OSError as exc:
            envelope["errors"].append(
                f"failed to write --output {output_path}: {exc}"
            )
            envelope["ok"] = False
    return envelope


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Still Moving Market candidate quality "
            "diagnostic.  For each curated candidate, reports "
            "whether the row is defensible against five known "
            "weakness axes: ticker quality, price_cache coverage, "
            "benchmark-adjusted evidence on file, persistence "
            "signal on file, and narrative uniqueness.  Does NOT "
            "change the shipped still-moving logic.  No DB writes, "
            "no provider, no LLM, no FastAPI surface.  Conservative "
            "wording: shape only, never a verdict."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help=(
            "Accepted for ergonomic parity with sibling scripts.  "
            "Output is always JSON."
        ),
    )
    parser.add_argument(
        "--yaml-path", dest="yaml_path",
        default=_DEFAULT_YAML_PATH,
        help=(
            f"Path to the curated-event YAML archive "
            f"(default {_DEFAULT_YAML_PATH})."
        ),
    )
    parser.add_argument(
        "--evidence-artifact", dest="evidence_artifact_path",
        default=_DEFAULT_EVIDENCE_ARTIFACT_PATH,
        help=(
            f"Path to the freeze-candidate evidence artifact "
            f"(default {_DEFAULT_EVIDENCE_ARTIFACT_PATH})."
        ),
    )
    parser.add_argument(
        "--persistence-signals", dest="persistence_signals_path",
        default=_DEFAULT_PERSISTENCE_SIGNALS_PATH,
        help=(
            "Optional path to a JSON mapping event_id -> "
            "persistence signal label.  When omitted, every "
            "candidate surfaces 'no_persistence_signal'."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to the events DB.  Defaults to "
            "db.DB_FILE.  Read-only by construction."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the diagnostic has no filesystem side "
            "effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_section_c_still_moving_quality_diagnostic(
        yaml_path=args.yaml_path,
        db_path=args.db_path,
        evidence_artifact_path=args.evidence_artifact_path,
        persistence_signals_path=args.persistence_signals_path,
        output_path=args.output_path,
    )
    print(_render_json(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_section_c_still_moving_quality_diagnostic",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
