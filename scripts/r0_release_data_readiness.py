"""R0 release-data readiness probe and report (``r0-release-register-v1``).

One bounded, zero-cost data-readiness proof for historical CPI and
Employment Situation releases: can the flow

    scheduled release -> actual / prior / revised prior / consensus
    -> point-in-time surprise -> future event-study eligibility

be supported reproducibly, with visible missingness and no look-ahead?
This slice normalizes the COMPLETE historical range available from the
selected zero-cost sources, counts every layer separately per family
and per calendar year, inspects real distributions, and emits exactly
one READY / NOT READY verdict per family.  It computes no asset
reaction, no statistic beyond descriptive counts and deltas, and no
surprise threshold.

Inputs: the gitignored local source capture written by
``scripts/r0_release_sources.run_capture`` (pinned Wayback snapshots
of the BLS schedule pages + ALFRED vintage matrices).  Output: the
tracked ``stats/R0_RELEASE_DATA_READINESS.md``.  Report generation is
deterministic for a given capture: every timestamp in the report comes
from the capture metadata, never from a clock read at render time.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from scripts import r0_release_register as r0r  # noqa: E402
from scripts import r0_release_sources as r0s  # noqa: E402

CAPTURE_DIR = ROOT / "g_state_cache" / "r0_release_source_cache"
REPORT_PATH = ROOT / "stats" / "R0_RELEASE_DATA_READINESS.md"

DEFAULT_START_YEAR = 2008  # first archived-snapshot year of both pages

# The consensus layer was surveyed source-by-source; no zero-cost,
# license-clean, reproducible source of PRE-RELEASE, per-release
# consensus history exists.  Model nowcasts are excluded on principle:
# an inferred consensus is not a consensus.
CONSENSUS_SOURCE_SURVEY: tuple[dict[str, str], ...] = (
    {"source": "FRED / ALFRED catalog",
     "fields": "actual, prior, revised prior (vintages); no consensus "
               "series exists for these releases",
     "depth": "vintages to 1949-1972 depending on series",
     "timestamp_precision": "vintage date (daily)",
     "revision_behavior": "full vintage record",
     "terms": "free registered key; redistribution of derived counts "
              "permitted",
     "reproducibility": "high (stable API, stable identifiers)",
     "failure_modes": "vintage-date vs release-date misalignment",
     "verdict": "supplies values; supplies no consensus"},
    {"source": "Philadelphia Fed Survey of Professional Forecasters",
     "fields": "quarterly-average forecasts (CPI inflation rate, "
               "payroll employment averages)",
     "depth": "1968+ (quarterly)",
     "timestamp_precision": "survey deadline, mid-quarter",
     "revision_behavior": "survey files are final",
     "terms": "free, documented",
     "reproducibility": "high",
     "failure_modes": "wrong granularity: quarterly averages are not "
                      "per-release monthly prints; deadlines do not "
                      "align with individual release timestamps",
     "verdict": "structurally incompatible with per-release surprise"},
    {"source": "Cleveland Fed inflation nowcasts",
     "fields": "model nowcasts of CPI before each release",
     "depth": "2014+",
     "timestamp_precision": "daily",
     "revision_behavior": "archived",
     "terms": "free",
     "reproducibility": "high",
     "failure_modes": "a model nowcast is an inferred expectation, not "
                      "a survey consensus; using it would substitute a "
                      "constructed input for the field being tested",
     "verdict": "excluded on principle (inferred consensus)"},
    {"source": "commercial economic calendars (survey medians from "
               "Bloomberg / Reuters / Dow Jones lineage; web mirrors)",
     "fields": "per-release consensus, actual, prior",
     "depth": "varies, roughly 2007+ on web mirrors",
     "timestamp_precision": "per release",
     "revision_behavior": "opaque",
     "terms": "licensed or terms-restricted; scraping mirrors violates "
              "their terms of use",
     "reproducibility": "low for mirrors (no stable archive, opaque "
                        "provenance); licensed feeds are not zero-cost",
     "failure_modes": "cost, licensing, unverifiable provenance",
     "verdict": "not zero-cost / not license-clean"},
)

_CONSENSUS_REASON = ("no zero-cost reproducible point-in-time consensus "
                     "source (see consensus source survey)")


def consensus_cell(series: Mapping[str, str]) -> dict[str, Any]:
    return r0r.value_cell(
        value=None, status="source_unavailable", unit=series["unit"],
        seasonal_adjustment=series["seasonal_adjustment"],
        measure_kind=series["measure_kind"], vintage_date=None,
        reason=_CONSENSUS_REASON)


# ---------------------------------------------------------------------------
# Register construction from the local capture
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_report_payload(capture_dir: Path = CAPTURE_DIR
                         ) -> dict[str, Any]:
    """Assemble the full payload from the local capture (offline)."""
    capture_dir = Path(capture_dir)
    meta = _load_json(capture_dir / "capture_meta.json")
    cutoff_date = str(meta["retrieved_at"])[:10]
    start_year = int(meta["start_year"])

    records: list[dict[str, Any]] = []
    schedule_stats: dict[str, dict[str, Any]] = {}
    for family in r0r.FAMILIES:
        snapshots: list[tuple[str, list[dict[str, Any]]]] = []
        rejected_rows: list[dict[str, Any]] = []
        for stamp in meta["schedule_snapshots"][family]:
            text = (capture_dir / f"schedule_{family}_{stamp}.htm"
                    ).read_text(encoding="utf-8", errors="replace")
            entries, rejected = r0s.parse_schedule_html(
                text, release_name=r0r.RELEASE_NAMES[family])
            snapshots.append((f"wayback:{stamp}", entries))
            rejected_rows.extend(
                dict(r, snapshot=f"wayback:{stamp}") for r in rejected)
        merged = r0s.merge_schedule_attestations(snapshots)
        in_scope = [e for e in merged
                    if f"{start_year}-01-01" <= e["release_date"]
                    <= cutoff_date]
        future_excluded = sum(1 for e in merged
                              if e["release_date"] > cutoff_date)
        before_scope = sum(1 for e in merged
                           if e["release_date"] < f"{start_year}-01-01")

        by_date = Counter(e["release_date"] for e in in_scope)
        collisions = sorted(d for d, n in by_date.items() if n > 1)
        usable = [e for e in in_scope
                  if e["release_date"] not in collisions]

        schedule_stats[family] = {
            "attempted_rows": len(in_scope),
            "rejected_rows": len(rejected_rows),
            "rejected_samples": rejected_rows[:8],
            "future_scheduled_excluded": future_excluded,
            "before_capture_scope": before_scope,
            "release_date_collisions": collisions,
            "snapshot_count": len(snapshots),
        }

        for series in r0r.SERIES[family]:
            series_id = series["series_id"]
            vintage_dates = r0s.parse_vintagedates(_load_json(
                capture_dir / f"alfred_vintagedates_{series_id}.json"))
            matrix: dict[str, dict[str, float]] = {}
            for chunk in sorted(capture_dir.glob(
                    f"alfred_matrix_{series_id}_*.json")):
                part = r0s.parse_vintage_matrix(_load_json(chunk),
                                                series_id=series_id)
                for period, cells in part.items():
                    matrix.setdefault(period, {}).update(cells)
            for entry in usable:
                cells = r0s.extract_release_values(
                    series=series, release_date=entry["release_date"],
                    reference_period=entry["reference_period"],
                    matrix=matrix, vintage_dates=vintage_dates)
                records.append(r0r.normalize_release(
                    family=family, series=series,
                    schedule_entry={
                        "reference_period": entry["reference_period"],
                        "release_date": entry["release_date"],
                        "release_time_local":
                            entry["release_time_local"],
                        "source_snapshots": entry["attested_by"],
                        "schedule_conflicts":
                            entry["schedule_conflicts"],
                    },
                    actual=cells["actual"], prior=cells["prior"],
                    revised_prior=cells["revised_prior"],
                    consensus=consensus_cell(series),
                    source_reference={
                        "schedule": meta["sources"]
                        [f"schedule_{family}"]["page"]
                        + " (pinned Wayback snapshots)",
                        "values": f"ALFRED vintage API series "
                                  f"{series_id}",
                    },
                    source_timestamp=str(meta["retrieved_at"]),
                    retrieval_method="bls_schedule_archive_snapshot+"
                                     "alfred_vintage_api"))

    register = r0r.build_register(records)
    for family in r0r.FAMILIES:
        family_records = [r for r in register if r["family"] == family]
        roster = len(r0r.SERIES[family])
        identities = {r["release_id"] for r in family_records}
        if len(family_records) != roster * len(identities):
            raise RuntimeError(
                f"{family}: register roster incomplete - "
                f"{len(family_records)} records for {len(identities)} "
                f"releases x {roster} series; refusing to count")
    counters = coverage_counters(register, {
        f: {"attempted_rows": schedule_stats[f]["attempted_rows"],
            "rejected_rows": schedule_stats[f]["rejected_rows"]}
        for f in r0r.FAMILIES})
    return {
        "register": register,
        "counters": counters,
        "schedule_stats": schedule_stats,
        "distributions": distribution_inspection(register),
        "verdicts": {f: evaluate_verdict(f, counters[f]["family"])
                     for f in r0r.FAMILIES},
        "provenance": {
            "capture": {
                "retrieved_at": meta["retrieved_at"],
                "start_year": meta["start_year"],
                "end_year": meta["end_year"],
                "schedule_snapshots": meta["schedule_snapshots"],
                "sources": meta["sources"],
                "file_count": len(meta["files"]),
            },
            "consensus_survey": CONSENSUS_SOURCE_SURVEY,
        },
    }


# ---------------------------------------------------------------------------
# Coverage counters
# ---------------------------------------------------------------------------

_LAYER_KEYS = (
    "attempted_releases", "identity_resolved", "timestamp_resolved",
    "actual_available", "prior_available", "consensus_available",
    "actual_prior_consensus_complete", "revision_ambiguous",
    "unit_incompatible", "source_unavailable", "fully_eligible")


def _release_layers(release_records: Sequence[Mapping[str, Any]]
                    ) -> dict[str, bool]:
    """Strict per-release layer booleans: a layer holds only when every
    series record of the release holds it.  Roster completeness (every
    registered series present per release) is enforced fail-loud by the
    build layer, not silently folded into these counts."""
    def field_ok(field: str) -> bool:
        return all(
            r[field]["status"] == "available" for r in release_records)

    timestamp_ok = all(
        r["scheduled_timestamp"] is not None for r in release_records)
    consensus_ok = field_ok("consensus")
    actual_ok = field_ok("actual")
    prior_ok = field_ok("prior")
    complete = actual_ok and prior_ok and consensus_ok
    ambiguous = any(r["revision_status"] == "revision_ambiguous"
                    for r in release_records)
    unit_bad = any(r["availability_status"] == "unit_incompatible"
                   for r in release_records)
    source_bad = any(r["availability_status"] == "source_unavailable"
                     for r in release_records)
    return {
        "timestamp_resolved": timestamp_ok,
        "actual_available": actual_ok,
        "prior_available": prior_ok,
        "consensus_available": consensus_ok,
        "actual_prior_consensus_complete": complete,
        "revision_ambiguous": ambiguous,
        "unit_incompatible": unit_bad,
        "source_unavailable": source_bad,
        "fully_eligible": (timestamp_ok and complete and not ambiguous
                           and not unit_bad and not source_bad),
    }


def coverage_counters(register: Sequence[Mapping[str, Any]],
                      schedule_stats: Mapping[str, Mapping[str, int]]
                      ) -> dict[str, Any]:
    """Mandated layer counters per family, per series, per year."""
    out: dict[str, Any] = {}
    for family in r0r.FAMILIES:
        family_records = [r for r in register if r["family"] == family]
        releases: dict[str, list[Mapping[str, Any]]] = {}
        for record in family_records:
            releases.setdefault(record["release_id"], []).append(record)

        stats = schedule_stats.get(family, {})
        family_counts: dict[str, int] = {key: 0 for key in _LAYER_KEYS}
        family_counts["attempted_releases"] = (
            int(stats.get("attempted_rows", 0))
            + int(stats.get("rejected_rows", 0)))
        family_counts["identity_resolved"] = len(releases)
        by_year: dict[str, dict[str, int]] = {}

        for release_id in sorted(releases):
            layers = _release_layers(releases[release_id])
            year = releases[release_id][0]["release_date"][:4]
            bucket = by_year.setdefault(year, {
                key: 0 for key in _LAYER_KEYS})
            bucket["attempted_releases"] += 1
            bucket["identity_resolved"] += 1
            for key, ok in layers.items():
                if ok:
                    family_counts[key] += 1
                    bucket[key] += 1

        series_counts: dict[str, dict[str, int]] = {}
        for series in r0r.SERIES[family]:
            sid = series["series_id"]
            recs = [r for r in family_records if r["series_id"] == sid]
            series_counts[sid] = {
                "records": len(recs),
                "actual_available": sum(
                    r["actual"]["status"] == "available" for r in recs),
                "prior_available": sum(
                    r["prior"]["status"] == "available" for r in recs),
                "revised_prior_available": sum(
                    r["revised_prior"]["status"] == "available"
                    for r in recs),
                "consensus_available": sum(
                    r["consensus"]["status"] == "available"
                    for r in recs),
                "prior_revised": sum(
                    r["revision_status"] == "prior_revised"
                    for r in recs),
                "prior_unrevised": sum(
                    r["revision_status"] == "prior_unrevised"
                    for r in recs),
                "revision_ambiguous": sum(
                    r["revision_status"] == "revision_ambiguous"
                    for r in recs),
            }

        out[family] = {"family": family_counts,
                       "series": series_counts,
                       "by_year": {y: by_year[y]
                                   for y in sorted(by_year)}}
    return out


# ---------------------------------------------------------------------------
# Distribution inspection (descriptive only; no threshold, no
# classification)
# ---------------------------------------------------------------------------


def _stats(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    median = (ordered[mid] if n % 2 else
              (ordered[mid - 1] + ordered[mid]) / 2.0)
    return {
        "count": n,
        "min": round(ordered[0], 6),
        "max": round(ordered[-1], 6),
        "mean": round(sum(ordered) / n, 6),
        "median": round(median, 6),
    }


def _decimals(value: float) -> int:
    text = repr(float(value))
    return len(text.split(".")[1]) if "." in text else 0


def distribution_inspection(register: Sequence[Mapping[str, Any]]
                            ) -> dict[str, Any]:
    """Observed distributions from as-published values only."""
    out: dict[str, Any] = {}
    for family in r0r.FAMILIES:
        for series in r0r.SERIES[family]:
            sid = series["series_id"]
            recs = [r for r in register if r["series_id"] == sid]
            revision_deltas = [
                r["revised_prior"]["value"] - r["prior"]["value"]
                for r in recs
                if r["revised_prior"]["status"] == "available"
                and r["prior"]["status"] == "available"]
            changes = [
                r["actual"]["value"] - r["revised_prior"]["value"]
                for r in recs
                if r["actual"]["status"] == "available"
                and r["revised_prior"]["status"] == "available"]
            pct_changes = [
                100.0 * (r["actual"]["value"]
                         / r["revised_prior"]["value"] - 1.0)
                for r in recs
                if r["actual"]["status"] == "available"
                and r["revised_prior"]["status"] == "available"
                and r["revised_prior"]["value"] != 0.0]
            complete = [
                r for r in recs
                if all(r[f]["status"] == "available"
                       for f in ("actual", "prior", "consensus"))]
            out[sid] = {
                "family": family,
                "unit": series["unit"],
                "revision_delta": _stats(revision_deltas),
                "revisions_nonzero": sum(
                    1 for d in revision_deltas if d != 0.0),
                "actual_minus_revised_prior": _stats(changes),
                "actual_pct_change_vs_revised_prior":
                    _stats(pct_changes),
                "decimals_observed": max(
                    (_decimals(r["actual"]["value"]) for r in recs
                     if r["actual"]["status"] == "available"),
                    default=0),
                "actual_minus_consensus": {
                    "count": len(complete),
                    "note": ("not computable: no release carries a "
                             "point-in-time consensus value"
                             if not complete else "computed")},
            }
    return out


# ---------------------------------------------------------------------------
# Verdict rule
# ---------------------------------------------------------------------------


def evaluate_verdict(family: str, counters: Mapping[str, int]
                     ) -> dict[str, Any]:
    """Structural readiness rule.  A blocker is a load-bearing layer
    with ZERO coverage; no numeric coverage threshold is invented."""
    blockers: list[str] = []
    if counters["identity_resolved"] == 0:
        blockers.append("release identity: zero identity-resolved "
                        "releases")
    if counters["timestamp_resolved"] == 0:
        blockers.append("resolved release timestamps: zero releases "
                        "with an unambiguous scheduled timestamp")
    if counters["actual_available"] == 0:
        blockers.append("point-in-time actual: zero releases with a "
                        "release-day vintage actual")
    if counters["prior_available"] == 0:
        blockers.append("point-in-time prior: zero releases with an "
                        "originally-published prior")
    if counters["consensus_available"] == 0:
        blockers.append(
            "point-in-time consensus: zero releases carry any "
            "zero-cost reproducible pre-release consensus value; the "
            "surprise column of the intended design cannot be built")
    if counters["fully_eligible"] == 0:
        blockers.append("eligible denominator: zero releases pass the "
                        "structural eligibility gate")
    return {"family": family,
            "verdict": "READY" if not blockers else "NOT READY",
            "blockers": blockers}


# ---------------------------------------------------------------------------
# Deterministic report
# ---------------------------------------------------------------------------


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]]
           ) -> list[str]:
    lines = ["| " + " | ".join(str(h) for h in headers) + " |",
             "|" + "---|" * len(headers)]
    lines.extend("| " + " | ".join(str(c) for c in row) + " |"
                 for row in rows)
    return lines


def _stats_line(stats: Mapping[str, Any]) -> str:
    if stats.get("count", 0) == 0:
        return "count 0"
    return (f"count {stats['count']}, min {stats['min']}, max "
            f"{stats['max']}, mean {stats['mean']}, median "
            f"{stats['median']}")


def render_report(payload: Mapping[str, Any]) -> str:
    counters = payload["counters"]
    distributions = payload["distributions"]
    verdicts = payload["verdicts"]
    provenance = payload["provenance"]
    register = payload["register"]
    schedule_stats = payload.get("schedule_stats", {})
    capture = provenance["capture"]

    L: list[str] = []
    L.append("# R0 - CPI and Employment release-surprise data readiness")
    L.append("")
    L.append(f"Contract: `{r0r.R0_CONTRACT}`. Capture retrieved at "
             f"{capture.get('retrieved_at')} (all report content "
             f"derives from that pinned capture; regeneration from "
             f"the same capture is byte-identical). Scope: scheduled "
             f"U.S. CPI and Employment Situation releases, capture "
             f"years {capture.get('start_year')}-"
             f"{capture.get('end_year')}. This is a data-readiness "
             f"proof only: no asset reaction, no event study, no "
             f"surprise threshold, and no statistical conclusion "
             f"appears here.")
    L.append("")

    # --- data contract ------------------------------------------------------
    L.append("## Data contract")
    L.append("")
    L.append("One record per (release, series). Fields: release_id "
             "(`family:release_date`), family, release_name, series_id, "
             "measure, reference_period, release_date, "
             "scheduled_timestamp (ISO-8601 with America/New_York "
             "offset), scheduled_timezone, actual, prior, "
             "revised_prior, consensus (each an explicit value cell "
             "with status, vintage provenance and reason), unit, "
             "seasonal_adjustment, measure_kind, frequency, "
             "source_reference, source_timestamp, retrieval_method, "
             "revision_status, availability_status, missing_reason, "
             "schedule_attestation.")
    L.append("")
    L.append("Three prior layers stay permanently distinct: `prior` is "
             "the previous reference month as originally published "
             "(its first vintage, strictly before this release); "
             "`revised_prior` is the same month as shown in this "
             "release's own vintage; the latest revised historical "
             "value is not a field of this contract and may never "
             "enter a point-in-time computation. A vintage after the "
             "release date can never populate a point-in-time field "
             "(hard construction error). Availability vocabulary: "
             + ", ".join(f"`{s}`" for s in r0r.AVAILABILITY_STATES)
             + ". Null alone never carries research meaning.")
    L.append("")
    L.append("Registered series:")
    L.append("")
    L.extend(_table(
        ("family", "series", "measure", "unit", "seasonal basis"),
        [(f, s["series_id"], s["measure"], s["unit"],
          s["seasonal_adjustment"])
         for f in r0r.FAMILIES for s in r0r.SERIES[f]]))
    L.append("")

    # --- source inventory ---------------------------------------------------
    L.append("## Source inventory")
    L.append("")
    L.append("Identity + scheduled-timestamp layer: the official BLS "
             "per-program schedule pages, read as PINNED Internet "
             "Archive (Wayback Machine) raw snapshots. A pinned "
             "snapshot is byte-reproducible; the archived page is "
             "still the primary BLS document. One snapshot attests "
             "roughly 14 forward months; one-or-two snapshots per "
             "calendar year give overlapping attestation. Direct "
             "www.bls.gov access from this environment is refused "
             "(HTTP 403 recorded below), which is an access-path "
             "failure mode, not a data gap.")
    L.append("")
    for family in r0r.FAMILIES:
        src = capture.get("sources", {}).get(f"schedule_{family}", {})
        stamps = capture.get("schedule_snapshots", {}).get(family, [])
        L.append(f"- {r0r.RELEASE_NAMES[family]}: `{src.get('page')}`; "
                 f"{len(stamps)} pinned snapshots "
                 f"({stamps[0][:4]}-{stamps[-1][:4]}), supplying "
                 f"reference month, release date and release time per "
                 f"row; revision behavior: reschedules appear as "
                 f"cross-snapshot conflicts and are never resolved "
                 f"silently." if stamps else
                 f"- {r0r.RELEASE_NAMES[family]}: no snapshots "
                 f"captured.")
    probe = capture.get("sources", {}).get("bls_direct_probe", {})
    L.append(f"- direct BLS probe evidence: "
             f"{json.dumps(probe, sort_keys=True)}")
    L.append("")
    L.append("Values layer: the ALFRED vintage layer of the official "
             "FRED API (authenticated free registered key; the key "
             "authenticates only and every recorded URL is redacted). "
             "A vintage dated on the release day carries the numbers "
             "published that morning; historical depth reaches "
             "1949-1972 depending on series; failure modes are "
             "vintage/release-date misalignment (counted explicitly "
             "below) and capture-scope truncation (bounded by the "
             "schedule layer's own start).")
    L.append("")
    L.append("Consensus layer survey (every zero-cost candidate "
             "evaluated):")
    L.append("")
    L.extend(_table(
        ("source", "fields", "depth", "terms", "reproducibility",
         "verdict"),
        [(s["source"], s["fields"], s["depth"], s["terms"],
          s["reproducibility"], s["verdict"])
         for s in provenance["consensus_survey"]]))
    L.append("")

    # --- coverage denominators ---------------------------------------------
    L.append("## Coverage denominators")
    L.append("")
    for family in r0r.FAMILIES:
        fam = counters[family]["family"]
        L.append(f"### {r0r.RELEASE_NAMES[family]} ({family})")
        L.append("")
        L.extend(_table(("layer", "count"),
                        [(k, fam[k]) for k in _LAYER_KEYS]))
        stats = schedule_stats.get(family, {})
        if stats:
            L.append("")
            L.append(f"- schedule snapshots parsed: "
                     f"{stats.get('snapshot_count')}; rejected schedule "
                     f"rows: {stats.get('rejected_rows')}; "
                     f"future-scheduled entries beyond the capture "
                     f"cutoff (excluded): "
                     f"{stats.get('future_scheduled_excluded')}; "
                     f"entries before the capture scope (excluded): "
                     f"{stats.get('before_capture_scope')}; same-day "
                     f"release-date collisions (excluded, listed): "
                     f"{stats.get('release_date_collisions')}")
        L.append("")
        L.append("Per series:")
        L.append("")
        series_counts = counters[family]["series"]
        L.extend(_table(
            ("series", "records", "actual", "prior", "revised prior",
             "consensus", "prior revised", "prior unrevised",
             "revision ambiguous"),
            [(sid, c["records"], c["actual_available"],
              c["prior_available"], c["revised_prior_available"],
              c["consensus_available"], c["prior_revised"],
              c["prior_unrevised"], c["revision_ambiguous"])
             for sid, c in sorted(series_counts.items())]))
        L.append("")
        L.append("By calendar year (release year; strict all-series "
                 "basis):")
        L.append("")
        L.extend(_table(
            ("year", "attempted", "timestamp", "actual", "prior",
             "consensus", "complete a/p/c", "fully eligible"),
            [(year, b["attempted_releases"], b["timestamp_resolved"],
              b["actual_available"], b["prior_available"],
              b["consensus_available"],
              b["actual_prior_consensus_complete"],
              b["fully_eligible"])
             for year, b in counters[family]["by_year"].items()]))
        L.append("")

    # --- availability and missingness --------------------------------------
    L.append("## Availability and missingness")
    L.append("")
    for family in r0r.FAMILIES:
        histogram = Counter(
            r["availability_status"] for r in register
            if r["family"] == family)
        L.append(f"- {family} record availability histogram: "
                 + ", ".join(f"{k}: {v}" for k, v in
                             sorted(histogram.items())))
    L.append("")
    L.append("Every non-available record carries its own "
             "missing_reason; the dominant reasons per family:")
    L.append("")
    for family in r0r.FAMILIES:
        reasons = Counter()
        for r in register:
            if r["family"] == family and r["missing_reason"]:
                for part in r["missing_reason"].split("; "):
                    pattern = part.split(" 2")[0].rstrip(" :,")
                    reasons[pattern] += 1
        top = reasons.most_common(6)
        L.append(f"- {family} (top {len(top)} reason patterns of "
                 f"{len(reasons)}):")
        for reason, count in top:
            L.append(f"  - {count}x {reason}")
    L.append("")

    # --- revision handling --------------------------------------------------
    L.append("## Revision handling")
    L.append("")
    L.append("The original prior is read from the previous release's "
             "own vintage and is immutable; the revised prior is read "
             "from this release's vintage; their difference is the "
             "observed within-release revision. When only one side is "
             "available the relation is `revision_ambiguous` and the "
             "release is excluded from the eligible denominator "
             "rather than repaired. Later vintages (annual seasonal "
             "recalculations, benchmark revisions) never overwrite "
             "any stored field.")
    L.append("")
    for family in r0r.FAMILIES:
        for series in r0r.SERIES[family]:
            sid = series["series_id"]
            d = distributions[sid]
            L.append(f"- {sid}: revision delta "
                     f"({_stats_line(d['revision_delta'])}); nonzero "
                     f"revisions: {d['revisions_nonzero']} of "
                     f"{d['revision_delta'].get('count', 0)}")
    L.append("")

    # --- timestamp handling -------------------------------------------------
    L.append("## Timestamp handling")
    L.append("")
    L.append("Scheduled timestamps combine the attested schedule date "
             "and local release time with the America/New_York zone "
             "into an explicit-offset ISO-8601 instant. A missing or "
             "unparseable time, or conflicting cross-snapshot "
             "attestations (reschedules), fail closed as "
             "`timestamp_unresolved`; nothing falls back to a "
             "convention. Release-day alignment against the values "
             "layer is enforced separately: an actual may come only "
             "from a vintage dated exactly on the attested release "
             "date, so a schedule/vintage mismatch surfaces as "
             "`missing_actual` with the mismatching date in the "
             "reason, never as a silently shifted join.")
    L.append("")
    for family in r0r.FAMILIES:
        fam = counters[family]["family"]
        distinct_conflicted = len({
            r["release_id"] for r in register
            if r["family"] == family
            and r["schedule_attestation"]["schedule_conflicts"]})
        L.append(f"- {family}: timestamp resolved "
                 f"{fam['timestamp_resolved']} of "
                 f"{fam['identity_resolved']} identity-resolved "
                 f"releases; releases with conflicting schedule "
                 f"attestations: {distinct_conflicted}")
    L.append("")

    # --- unit compatibility -------------------------------------------------
    L.append("## Unit compatibility")
    L.append("")
    L.append("Each series carries one declared unit, one seasonal "
             "basis and one measure kind; a record mixing any of them "
             "fails closed as `unit_incompatible` with every numeric "
             "field demoted. Seasonally adjusted and unadjusted CPI "
             "are separate series and never share a record; monthly "
             "levels and derived monthly changes are distinct measure "
             "kinds and cannot be stored in one field.")
    L.append("")
    for family in r0r.FAMILIES:
        for series in r0r.SERIES[family]:
            sid = series["series_id"]
            L.append(f"- {sid}: unit `{series['unit']}`, basis "
                     f"{series['seasonal_adjustment']}; observed "
                     f"decimal places in as-published values: "
                     f"{distributions[sid]['decimals_observed']}; "
                     f"unit-incompatible records: 0" if
                     counters[family]['family']['unit_incompatible']
                     == 0 else
                     f"- {sid}: unit `{series['unit']}` - "
                     f"unit-incompatible records present, see "
                     f"denominators")
    L.append("")

    # --- point-in-time risks ------------------------------------------------
    L.append("## Point-in-time risks")
    L.append("")
    L.append("Field classification (a field classified retrospective, "
             "latest-revised or uncertain may not enter a future "
             "point-in-time surprise calculation):")
    L.append("")
    L.extend(_table(
        ("field", "classification"),
        [("scheduled_timestamp", "known at scheduled release "
          "(published in the annual BLS schedule, attested by "
          "pre-release snapshots where available)"),
         ("actual", "published in the release document (release-day "
          "vintage)"),
         ("prior (original)", "published at the previous release; "
          "known before this release"),
         ("revised_prior", "published in the release document "
          "(release-day vintage)"),
         ("consensus", "uncertain: no compliant source exists; the "
          "field stays explicitly missing"),
         ("latest revised value", "latest-revised: excluded from the "
          "contract by design")]))
    L.append("")
    L.append("Residual risks kept visible rather than repaired: "
             "(1) a Wayback snapshot taken after a reschedule can "
             "attest only the revised date - conflicts are counted "
             "and fail closed; (2) ALFRED vintage dates can lag or "
             "lead the BLS release date - such releases surface as "
             "missing_actual with the date in the reason and are "
             "excluded, not shifted; (3) snapshot coverage begins in "
             "2008, so earlier releases have deep vintage values but "
             "no source-pinned schedule attestation and stay outside "
             "this register; (4) intraday timestamp precision rests "
             "on the schedule's local release time - no trade-level "
             "timestamping is claimed.")
    L.append("")

    # --- distribution observations -----------------------------------------
    L.append("## Distribution observations")
    L.append("")
    L.append("Descriptive scales only, from as-published values; no "
             "threshold, no classification, no standardization is "
             "defined here.")
    L.append("")
    for family in r0r.FAMILIES:
        for series in r0r.SERIES[family]:
            sid = series["series_id"]
            d = distributions[sid]
            L.append(f"- {sid} ({family}, `{d['unit']}`):")
            L.append(f"  - actual minus revised prior: "
                     f"{_stats_line(d['actual_minus_revised_prior'])}")
            L.append(f"  - actual percent change vs revised prior: "
                     f"{_stats_line(
                         d['actual_pct_change_vs_revised_prior'])}")
            L.append(f"  - within-release revision delta: "
                     f"{_stats_line(d['revision_delta'])}")
            L.append(f"  - actual minus consensus: "
                     f"{d['actual_minus_consensus']['count']} records "
                     f"({d['actual_minus_consensus']['note']})")
    L.append("")

    # --- proposed gate ------------------------------------------------------
    L.append("## Proposed future eligibility gate")
    L.append("")
    L.append("Minimum defensible gate, derived from the observed "
             "layers (no numeric coverage threshold is invented): a "
             "release is eligible only when its identity is "
             "snapshot-attested without conflict, its timestamp is "
             "resolved, its actual and revised prior come from the "
             "release-day vintage, its original prior comes from a "
             "strictly earlier vintage, a point-in-time consensus "
             "value exists, and all values share one unit, basis and "
             "measure kind. This is exactly the `fully_eligible` "
             "counter above; every excluded release is preserved with "
             "its reason. The gate is sufficient for the intended "
             "descriptive release-surprise question because each "
             "clause removes one named look-ahead or conflation "
             "channel; it is applied uniformly to both families.")
    L.append("")

    # --- verdicts -----------------------------------------------------------
    L.append("## Readiness verdict")
    L.append("")
    for family in r0r.FAMILIES:
        L.append(f"- {family}: {verdicts[family]['verdict']}")
    L.append("")
    for family in r0r.FAMILIES:
        verdict = verdicts[family]
        if verdict["blockers"]:
            fam = counters[family]["family"]
            years = sorted(counters[family]["by_year"])
            L.append(f"### {family} blockers")
            L.append("")
            for blocker in verdict["blockers"]:
                L.append(f"- {blocker}")
            L.append(f"- affected denominator: "
                     f"{fam['attempted_releases']} attempted releases "
                     f"({fam['identity_resolved']} identity-resolved), "
                     f"years {years[0]}-{years[-1]}" if years else
                     "- affected denominator: 0 attempted releases")
            L.append("- smallest realistic repair: a licensed "
                     "per-release consensus history (cost / licensing) "
                     "or a manually adjudicated point-in-time capture "
                     "of archived pre-release survey medians (manual "
                     "adjudication); prospective capture going forward "
                     "is zero-cost but builds history only from now "
                     "on. No repair is attempted here and nothing is "
                     "built around the missing field.")
            L.append("")

    # --- non-claims ---------------------------------------------------------
    L.append("## Non-claims")
    L.append("")
    L.append("- No event study, asset reaction, or estimate of any "
             "economic relationship was computed anywhere in R0.")
    L.append("- No surprise threshold, classification, or "
             "standardization was defined.")
    L.append("- Source availability is a feasibility property only; "
             "it is not evidence that any release moves anything.")
    L.append("- No predictive, causal, significant, or tradeable claim "
             "is made, and none is implied.")
    L.append("- No synthetic value was created, no gap was filled, no "
             "release was hand-selected: the universe is every "
             "schedule-attested release in the capture scope.")
    L.append("- A NOT READY verdict prices the missing layer; it says "
             "nothing about the economic importance of either family.")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-sources", action="store_true")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--emit", action="store_true")
    parser.add_argument("--dest", default=None,
                        help="alternate capture directory")
    parser.add_argument("--start-year", type=int,
                        default=DEFAULT_START_YEAR)
    parser.add_argument("--end-year", type=int, default=None)
    args = parser.parse_args(argv)
    dest = Path(args.dest) if args.dest else CAPTURE_DIR

    if args.probe_sources:
        result = {"bls_direct": r0s.probe_direct_bls()}
        sys.stdout.write(json.dumps(result, indent=1, sort_keys=True)
                         + "\n")
        return 0
    if args.fetch:
        retrieved_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds")
        end_year = args.end_year or int(retrieved_at[:4])
        meta = r0s.run_capture(dest, start_year=args.start_year,
                               end_year=end_year,
                               retrieved_at=retrieved_at)
        sys.stdout.write(f"captured {len(meta['files'])} files into "
                         f"{dest}\n")
        return 0
    if args.emit:
        payload = build_report_payload(dest)
        report = render_report(payload)
        REPORT_PATH.write_text(report, encoding="utf-8", newline="\n")
        import hashlib
        digest = hashlib.sha256(report.encode("utf-8")).hexdigest()
        sys.stdout.write(f"wrote {REPORT_PATH}\nreport sha256 "
                         f"{digest}\n")
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
