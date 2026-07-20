"""R0 source-parser and readiness-report tests (r0-release-register-v1).

Three input layers stay distinct (published-research test discipline):

* default-run fixtures below are verbatim excerpts of the captured real
  sources (Wayback-pinned BLS schedule pages; ALFRED vintage API JSON),
  trimmed but never reshaped;
* the tracked report test reads the committed
  ``stats/R0_RELEASE_DATA_READINESS.md`` artifact only;
* the full untracked source capture under ``g_state_cache/`` is consumed
  exclusively by the operator-run readiness script, never by this module.

No test here performs a network call, opens a database, or writes any
cache; the guards at the bottom enforce that mechanically.
"""

from __future__ import annotations

import json
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from scripts import r0_release_data_readiness as r0d
from scripts import r0_release_register as r0r
from scripts import r0_release_sources as r0s

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Verbatim source excerpts (captured 2026-07-20)
# ---------------------------------------------------------------------------

# bls.gov/schedule/news_release/cpi.htm, Wayback snapshot 20240427220534
# (raw id_ capture): title line plus the schedule table, trimmed to five
# real rows including the dotted and undotted month-abbreviation forms.
CPI_SCHEDULE_HTML = """<html><head>
<title>Schedule of Releases for the Consumer Price Index : U.S. Bureau of Labor Statistics</title>
</head><body>
<table class="release-list">
<thead>
<tr>
<th>Reference Month</th>
<th>Release Date</th>
<th>Release Time</th>
</tr>
</thead>
<tbody>
<tr class="release-list-even-row">
<td>December 2023</td>
<td>Jan. 11, 2024</td>
<td>08:30 AM</td>
</tr>
<tr class="release-list-odd-row">
<td>January 2024</td>
<td>Feb. 13, 2024</td>
<td>08:30 AM</td>
</tr>
<tr class="release-list-even-row">
<td>February 2024</td>
<td>Mar. 12, 2024</td>
<td>08:30 AM</td>
</tr>
<tr class="release-list-odd-row">
<td>March 2024</td>
<td>Apr. 10, 2024</td>
<td>08:30 AM</td>
</tr>
<tr class="release-list-even-row">
<td>April 2024</td>
<td>May 15, 2024</td>
<td>08:30 AM</td>
</tr>
</tbody>
</table>
</body></html>"""

# bls.gov/schedule/news_release/empsit.htm, Wayback snapshot (December
# 2024, raw id_ capture): the same table shape with CRLF line endings as
# served, trimmed to three real rows.
EMPSIT_SCHEDULE_HTML = (
    "<html><head>\r\n"
    "<title>Schedule of Releases for the Employment Situation : U.S. "
    "Bureau of Labor Statistics</title>\r\n"
    "</head><body>\r\n"
    "<table class=\"release-list\">\r\n<thead>\r\n<tr>\r\n"
    "<th>Reference Month</th>\r\n<th>Release Date</th>\r\n"
    "<th>Release Time</th>\r\n</tr>\r\n</thead>\r\n<tbody>\r\n"
    "<tr class=\"release-list-even-row\">\r\n<td>October 2024</td>\r\n"
    "<td>Nov. 01, 2024</td>\r\n<td>08:30 AM</td>\r\n</tr>\r\n"
    "<tr class=\"release-list-odd-row\">\r\n<td>November 2024</td>\r\n"
    "<td>Dec. 06, 2024</td>\r\n<td>08:30 AM</td>\r\n</tr>\r\n"
    "<tr class=\"release-list-even-row\">\r\n<td>December 2024</td>\r\n"
    "<td>Jan. 10, 2025</td>\r\n<td>08:30 AM</td>\r\n</tr>\r\n"
    "</tbody>\r\n</table>\r\n</body></html>\r\n")

# ALFRED fred/series/observations output_type=2 response for CPIAUCSL,
# observation window 2023-11-01..2024-02-29, realtime window
# 2024-02-13..2024-03-12 — captured verbatim (values are strings in the
# source; the 2024-02 observation exists only in the 2024-03-12 vintage).
ALFRED_CPI_MATRIX_PAYLOAD = {
    "realtime_start": "2024-02-13",
    "realtime_end": "2024-03-12",
    "observation_start": "2023-11-01",
    "observation_end": "2024-02-29",
    "units": "lin",
    "output_type": 2,
    "file_type": "json",
    "order_by": "observation_date",
    "sort_order": "asc",
    "count": 4,
    "offset": 0,
    "limit": 100000,
    "observations": [
        {"date": "2023-11-01", "CPIAUCSL_20240213": "308.024",
         "CPIAUCSL_20240312": "308.024"},
        {"date": "2023-12-01", "CPIAUCSL_20240213": "308.742",
         "CPIAUCSL_20240312": "308.742"},
        {"date": "2024-01-01", "CPIAUCSL_20240213": "309.685",
         "CPIAUCSL_20240312": "309.685"},
        {"date": "2024-02-01", "CPIAUCSL_20240312": "311.054"},
    ],
}

# Same endpoint for PAYEMS, observation window 2024-08-01..2024-11-30,
# realtime window 2024-11-01..2024-12-06 — captured verbatim; the
# 2024-10 observation was published at 159005 and revised to 159061.
ALFRED_PAYEMS_MATRIX_PAYLOAD = {
    "realtime_start": "2024-11-01",
    "realtime_end": "2024-12-06",
    "observation_start": "2024-08-01",
    "observation_end": "2024-11-30",
    "units": "lin",
    "output_type": 2,
    "file_type": "json",
    "order_by": "observation_date",
    "sort_order": "asc",
    "count": 4,
    "offset": 0,
    "limit": 100000,
    "observations": [
        {"date": "2024-08-01", "PAYEMS_20241101": "158770",
         "PAYEMS_20241206": "158770"},
        {"date": "2024-09-01", "PAYEMS_20241101": "158993",
         "PAYEMS_20241206": "159025"},
        {"date": "2024-10-01", "PAYEMS_20241101": "159005",
         "PAYEMS_20241206": "159061"},
        {"date": "2024-11-01", "PAYEMS_20241206": "159288"},
    ],
}

# fred/series/vintagedates shape (real excerpt of the CPIAUCSL list).
ALFRED_VINTAGEDATES_PAYLOAD = {
    "realtime_start": "1776-07-04",
    "realtime_end": "9999-12-31",
    "order_by": "vintage_date",
    "sort_order": "asc",
    "count": 3,
    "offset": 0,
    "limit": 10000,
    "vintage_dates": ["2024-02-13", "2024-03-12", "2024-04-10"],
}


def series_meta(series_id: str) -> dict:
    for family in r0r.FAMILIES:
        for s in r0r.SERIES[family]:
            if s["series_id"] == series_id:
                return s
    raise AssertionError(f"series {series_id} not registered")


# ---------------------------------------------------------------------------
# Schedule parsing
# ---------------------------------------------------------------------------


class TestScheduleParsing(unittest.TestCase):
    def test_parse_cpi_schedule_excerpt(self):
        entries, rejected = r0s.parse_schedule_html(
            CPI_SCHEDULE_HTML, release_name="Consumer Price Index")
        self.assertEqual(rejected, [])
        got = [(e["reference_period"], e["release_date"],
                e["release_time_local"]) for e in entries]
        self.assertEqual(got, [
            ("2023-12", "2024-01-11", "08:30"),
            ("2024-01", "2024-02-13", "08:30"),
            ("2024-02", "2024-03-12", "08:30"),
            ("2024-03", "2024-04-10", "08:30"),
            ("2024-04", "2024-05-15", "08:30"),
        ])

    def test_parse_employment_schedule_excerpt_with_crlf(self):
        entries, rejected = r0s.parse_schedule_html(
            EMPSIT_SCHEDULE_HTML, release_name="Employment Situation")
        self.assertEqual(rejected, [])
        got = [(e["reference_period"], e["release_date"],
                e["release_time_local"]) for e in entries]
        self.assertEqual(got, [
            ("2024-10", "2024-11-01", "08:30"),
            ("2024-11", "2024-12-06", "08:30"),
            ("2024-12", "2025-01-10", "08:30"),
        ])

    def test_malformed_rows_are_rejected_not_dropped(self):
        broken = CPI_SCHEDULE_HTML.replace("Mar. 12, 2024", "Mar. 99, 2024")
        broken = broken.replace("January 2024", "Sometime 2024")
        entries, rejected = r0s.parse_schedule_html(
            broken, release_name="Consumer Price Index")
        self.assertEqual(len(entries), 3)
        self.assertEqual(len(rejected), 2)
        reasons = " ".join(r["reason"] for r in rejected)
        self.assertIn("Mar. 99, 2024", json.dumps(rejected))
        self.assertIn("Sometime 2024", json.dumps(rejected))
        self.assertTrue(reasons)

    def test_wrong_page_fails_loudly(self):
        with self.assertRaises(ValueError):
            r0s.parse_schedule_html(
                CPI_SCHEDULE_HTML, release_name="Employment Situation")

    def test_afternoon_time_is_normalized_to_24h(self):
        html = CPI_SCHEDULE_HTML.replace("08:30 AM", "01:00 PM", 1)
        entries, rejected = r0s.parse_schedule_html(
            html, release_name="Consumer Price Index")
        self.assertEqual(rejected, [])
        self.assertEqual(entries[0]["release_time_local"], "13:00")


class TestScheduleAttestations(unittest.TestCase):
    def snapshot_entries(self):
        entries, _ = r0s.parse_schedule_html(
            CPI_SCHEDULE_HTML, release_name="Consumer Price Index")
        return entries

    def test_overlapping_snapshots_merge_with_attestation(self):
        e = self.snapshot_entries()
        merged = r0s.merge_schedule_attestations([
            ("wayback:20240427220534", e),
            ("wayback:20241231173152", e[2:]),
        ])
        by_ref = {m["reference_period"]: m for m in merged}
        self.assertEqual(len(merged), 5)
        self.assertEqual(by_ref["2024-02"]["attested_by"],
                         ["wayback:20240427220534",
                          "wayback:20241231173152"])
        self.assertEqual(by_ref["2024-02"]["schedule_conflicts"], [])
        self.assertEqual(by_ref["2023-12"]["attested_by"],
                         ["wayback:20240427220534"])

    def test_conflicting_dates_are_flagged_never_resolved_silently(self):
        e = self.snapshot_entries()
        moved = [dict(x) for x in e]
        moved[2] = dict(moved[2], release_date="2024-03-13")
        merged = r0s.merge_schedule_attestations([
            ("wayback:a", e), ("wayback:b", moved)])
        by_ref = {m["reference_period"]: m for m in merged}
        conflicts = by_ref["2024-02"]["schedule_conflicts"]
        self.assertTrue(conflicts)
        dates = {c["release_date"] for c in conflicts}
        self.assertEqual(dates, {"2024-03-12", "2024-03-13"})
        # unconflicted refs stay clean
        self.assertEqual(by_ref["2024-01"]["schedule_conflicts"], [])

    def test_merge_is_deterministic(self):
        e = self.snapshot_entries()
        a = r0s.merge_schedule_attestations([("s1", e), ("s2", e[1:])])
        b = r0s.merge_schedule_attestations([("s2", e[1:]), ("s1", e)])
        self.assertEqual(a, b)


# ---------------------------------------------------------------------------
# ALFRED vintage parsing and the point-in-time join
# ---------------------------------------------------------------------------


class TestVintageParsing(unittest.TestCase):
    def test_parse_vintagedates(self):
        got = r0s.parse_vintagedates(ALFRED_VINTAGEDATES_PAYLOAD)
        self.assertEqual(got, ["2024-02-13", "2024-03-12", "2024-04-10"])

    def test_parse_vintage_matrix_real_excerpt(self):
        matrix = r0s.parse_vintage_matrix(
            ALFRED_CPI_MATRIX_PAYLOAD, series_id="CPIAUCSL")
        self.assertEqual(matrix["2024-01"],
                         {"2024-02-13": 309.685, "2024-03-12": 309.685})
        self.assertEqual(matrix["2024-02"], {"2024-03-12": 311.054})

    def test_dot_marker_is_missing_not_error(self):
        payload = json.loads(json.dumps(ALFRED_CPI_MATRIX_PAYLOAD))
        payload["observations"][0]["CPIAUCSL_20240213"] = "."
        matrix = r0s.parse_vintage_matrix(payload, series_id="CPIAUCSL")
        self.assertNotIn("2024-02-13", matrix["2023-11"])
        self.assertIn("2024-03-12", matrix["2023-11"])

    def test_malformed_value_fails_closed(self):
        payload = json.loads(json.dumps(ALFRED_CPI_MATRIX_PAYLOAD))
        payload["observations"][0]["CPIAUCSL_20240213"] = "n/a"
        with self.assertRaises(ValueError):
            r0s.parse_vintage_matrix(payload, series_id="CPIAUCSL")

    def test_foreign_series_column_fails_closed(self):
        payload = json.loads(json.dumps(ALFRED_CPI_MATRIX_PAYLOAD))
        payload["observations"][0]["CPIAUCNS_20240213"] = "307.026"
        with self.assertRaises(ValueError):
            r0s.parse_vintage_matrix(payload, series_id="CPIAUCSL")


class TestPointInTimeJoin(unittest.TestCase):
    def cpi_matrix(self):
        return r0s.parse_vintage_matrix(
            ALFRED_CPI_MATRIX_PAYLOAD, series_id="CPIAUCSL")

    def payems_matrix(self):
        return r0s.parse_vintage_matrix(
            ALFRED_PAYEMS_MATRIX_PAYLOAD, series_id="PAYEMS")

    def test_cpi_join_extracts_point_in_time_cells(self):
        cells = r0s.extract_release_values(
            series=series_meta("CPIAUCSL"), release_date="2024-03-12",
            reference_period="2024-02", matrix=self.cpi_matrix(),
            vintage_dates=["2024-01-11", "2024-02-13", "2024-03-12"])
        self.assertEqual(cells["actual"]["value"], 311.054)
        self.assertEqual(cells["actual"]["vintage_date"], "2024-03-12")
        # prior = first vintage that ever contained 2024-01 (its own
        # release), strictly before this release date
        self.assertEqual(cells["prior"]["value"], 309.685)
        self.assertEqual(cells["prior"]["vintage_date"], "2024-02-13")
        self.assertEqual(cells["revised_prior"]["value"], 309.685)
        self.assertEqual(cells["revised_prior"]["vintage_date"],
                         "2024-03-12")

    def test_payems_join_separates_original_and_revised_prior(self):
        cells = r0s.extract_release_values(
            series=series_meta("PAYEMS"), release_date="2024-12-06",
            reference_period="2024-11", matrix=self.payems_matrix(),
            vintage_dates=["2024-10-04", "2024-11-01", "2024-12-06"])
        self.assertEqual(cells["actual"]["value"], 159288.0)
        self.assertEqual(cells["prior"]["value"], 159005.0)
        self.assertEqual(cells["prior"]["vintage_date"], "2024-11-01")
        self.assertEqual(cells["revised_prior"]["value"], 159061.0)

    def test_no_release_day_vintage_yields_explicit_missing(self):
        cells = r0s.extract_release_values(
            series=series_meta("CPIAUCSL"), release_date="2024-03-13",
            reference_period="2024-02", matrix=self.cpi_matrix(),
            vintage_dates=["2024-01-11", "2024-02-13", "2024-03-12"])
        self.assertEqual(cells["actual"]["status"], "missing")
        self.assertIsNone(cells["actual"]["value"])
        self.assertIn("no vintage", cells["actual"]["reason"])
        self.assertEqual(cells["revised_prior"]["status"], "missing")

    def test_prior_never_taken_from_release_day_or_later(self):
        matrix = self.cpi_matrix()
        # remove the 2024-02-13 vintage of the prior month so its first
        # available vintage is the release day itself
        del matrix["2024-01"]["2024-02-13"]
        cells = r0s.extract_release_values(
            series=series_meta("CPIAUCSL"), release_date="2024-03-12",
            reference_period="2024-02", matrix=matrix,
            vintage_dates=["2024-01-11", "2024-02-13", "2024-03-12"])
        self.assertEqual(cells["prior"]["status"], "missing")
        self.assertIsNone(cells["prior"]["value"])


# ---------------------------------------------------------------------------
# Coverage counters and verdict rule
# ---------------------------------------------------------------------------


def fixture_register():
    """Small register built from the captured cells through the real
    normalizer (mechanics only; the historical cohort lives in the
    operator capture, never here)."""
    consensus_reason = ("no zero-cost reproducible point-in-time "
                        "consensus source")
    cpi_cells = r0s.extract_release_values(
        series=series_meta("CPIAUCSL"), release_date="2024-03-12",
        reference_period="2024-02",
        matrix=r0s.parse_vintage_matrix(
            ALFRED_CPI_MATRIX_PAYLOAD, series_id="CPIAUCSL"),
        vintage_dates=["2024-01-11", "2024-02-13", "2024-03-12"])
    emp_cells = r0s.extract_release_values(
        series=series_meta("PAYEMS"), release_date="2024-12-06",
        reference_period="2024-11",
        matrix=r0s.parse_vintage_matrix(
            ALFRED_PAYEMS_MATRIX_PAYLOAD, series_id="PAYEMS"),
        vintage_dates=["2024-10-04", "2024-11-01", "2024-12-06"])
    records = []
    for family, series_id, cells, entry in (
        ("cpi", "CPIAUCSL", cpi_cells, {
            "reference_period": "2024-02", "release_date": "2024-03-12",
            "release_time_local": "08:30",
            "source_snapshots": ["wayback:20240427220534"],
            "schedule_conflicts": []}),
        ("employment", "PAYEMS", emp_cells, {
            "reference_period": "2024-11", "release_date": "2024-12-06",
            "release_time_local": "08:30",
            "source_snapshots": ["wayback:20241231"],
            "schedule_conflicts": []}),
    ):
        meta = series_meta(series_id)
        records.append(r0r.normalize_release(
            family=family, series=meta, schedule_entry=entry,
            actual=cells["actual"], prior=cells["prior"],
            revised_prior=cells["revised_prior"],
            consensus=r0r.value_cell(
                value=None, status="source_unavailable",
                unit=meta["unit"],
                seasonal_adjustment=meta["seasonal_adjustment"],
                measure_kind=meta["measure_kind"], vintage_date=None,
                reason=consensus_reason),
            source_reference={"schedule": "wayback", "values": "alfred"},
            source_timestamp="2026-07-20T00:00:00+00:00",
            retrieval_method="bls_schedule_archive_snapshot+"
                             "alfred_vintage_api"))
    return r0r.build_register(records)


class TestCoverageCounters(unittest.TestCase):
    def test_counters_report_each_layer_separately(self):
        register = fixture_register()
        schedule_stats = {
            "cpi": {"attempted_rows": 1, "rejected_rows": 0},
            "employment": {"attempted_rows": 1, "rejected_rows": 0},
        }
        counters = r0d.coverage_counters(register, schedule_stats)
        cpi = counters["cpi"]["family"]
        self.assertEqual(cpi["attempted_releases"], 1)
        self.assertEqual(cpi["identity_resolved"], 1)
        self.assertEqual(cpi["timestamp_resolved"], 1)
        self.assertEqual(cpi["actual_available"], 1)
        self.assertEqual(cpi["prior_available"], 1)
        self.assertEqual(cpi["consensus_available"], 0)
        self.assertEqual(cpi["actual_prior_consensus_complete"], 0)
        self.assertEqual(cpi["revision_ambiguous"], 0)
        self.assertEqual(cpi["unit_incompatible"], 0)
        self.assertEqual(cpi["source_unavailable"], 0)
        self.assertEqual(cpi["fully_eligible"], 0)
        self.assertEqual(counters["cpi"]["by_year"]["2024"]
                         ["attempted_releases"], 1)

    def test_counters_never_mix_families(self):
        register = fixture_register()
        schedule_stats = {
            "cpi": {"attempted_rows": 1, "rejected_rows": 0},
            "employment": {"attempted_rows": 1, "rejected_rows": 0},
        }
        counters = r0d.coverage_counters(register, schedule_stats)
        emp = counters["employment"]["family"]
        self.assertEqual(emp["attempted_releases"], 1)
        self.assertEqual(emp["actual_available"], 1)
        self.assertEqual(emp["consensus_available"], 0)


class TestVerdictRule(unittest.TestCase):
    def family_counters(self, **overrides):
        base = {
            "attempted_releases": 221, "identity_resolved": 221,
            "timestamp_resolved": 220, "actual_available": 219,
            "prior_available": 218, "consensus_available": 0,
            "actual_prior_consensus_complete": 0,
            "revision_ambiguous": 2, "unit_incompatible": 0,
            "source_unavailable": 0, "fully_eligible": 0,
        }
        base.update(overrides)
        return base

    def test_zero_consensus_blocks_readiness(self):
        verdict = r0d.evaluate_verdict("cpi", self.family_counters())
        self.assertEqual(verdict["verdict"], "NOT READY")
        self.assertTrue(any("consensus" in b for b in verdict["blockers"]))

    def test_zero_actual_blocks_readiness(self):
        verdict = r0d.evaluate_verdict(
            "cpi", self.family_counters(actual_available=0))
        self.assertEqual(verdict["verdict"], "NOT READY")
        self.assertTrue(any("actual" in b for b in verdict["blockers"]))

    def test_rule_can_pass_when_every_layer_is_nonzero(self):
        # minimal logic fixture proving the rule mechanics only; it makes
        # no claim that any real source reaches this state
        verdict = r0d.evaluate_verdict("cpi", self.family_counters(
            consensus_available=200, actual_prior_consensus_complete=200,
            fully_eligible=198))
        self.assertEqual(verdict["verdict"], "READY")
        self.assertEqual(verdict["blockers"], [])


# ---------------------------------------------------------------------------
# Deterministic report rendering
# ---------------------------------------------------------------------------


def fixture_payload():
    register = fixture_register()
    schedule_stats = {
        "cpi": {"attempted_rows": 1, "rejected_rows": 0},
        "employment": {"attempted_rows": 1, "rejected_rows": 0},
    }
    counters = r0d.coverage_counters(register, schedule_stats)
    return {
        "register": register,
        "counters": counters,
        "distributions": r0d.distribution_inspection(register),
        "verdicts": {f: r0d.evaluate_verdict(f, counters[f]["family"])
                     for f in r0r.FAMILIES},
        "provenance": {
            "capture": {"retrieved_at": "2026-07-20T00:00:00+00:00",
                        "snapshots": ["wayback:20240427220534"]},
            "consensus_survey": r0d.CONSENSUS_SOURCE_SURVEY,
        },
    }


class TestReportRendering(unittest.TestCase):
    REQUIRED_SECTIONS = (
        "## Data contract",
        "## Source inventory",
        "## Coverage denominators",
        "## Availability and missingness",
        "## Revision handling",
        "## Timestamp handling",
        "## Unit compatibility",
        "## Point-in-time risks",
        "## Distribution observations",
        "## Readiness verdict",
        "## Non-claims",
    )

    def test_report_is_deterministic(self):
        payload = fixture_payload()
        one = r0d.render_report(payload)
        two = r0d.render_report(payload)
        self.assertEqual(one, two)
        self.assertEqual(r0d.render_report(fixture_payload()), one)

    def test_report_contains_every_required_section(self):
        report = r0d.render_report(fixture_payload())
        for section in self.REQUIRED_SECTIONS:
            self.assertIn(section, report)

    def test_exactly_one_verdict_line_per_family(self):
        report = r0d.render_report(fixture_payload())
        lines = [ln for ln in report.splitlines()
                 if ln.startswith("- cpi: ") or
                 ln.startswith("- employment: ")]
        verdict_lines = [ln for ln in lines
                         if ln.endswith(": READY") or
                         ln.endswith(": NOT READY")]
        self.assertEqual(len(verdict_lines), 2)
        for ln in verdict_lines:
            self.assertRegex(ln, r"^- (cpi|employment): (READY|NOT READY)$")


# ---------------------------------------------------------------------------
# Tracked-report contract (reads the committed artifact only)
# ---------------------------------------------------------------------------


class TestTrackedReport(unittest.TestCase):
    REPORT = ROOT / "stats" / "R0_RELEASE_DATA_READINESS.md"

    def test_tracked_report_exists_and_carries_the_contract(self):
        text = self.REPORT.read_text(encoding="utf-8")
        self.assertIn("r0-release-register-v1", text)
        for section in TestReportRendering.REQUIRED_SECTIONS:
            self.assertIn(section, text)

    def test_tracked_report_has_one_explicit_verdict_per_family(self):
        text = self.REPORT.read_text(encoding="utf-8")
        verdicts = [ln for ln in text.splitlines()
                    if ln.startswith("- cpi: ") or
                    ln.startswith("- employment: ")]
        verdicts = [ln for ln in verdicts
                    if ln.endswith(": READY") or
                    ln.endswith(": NOT READY")]
        self.assertEqual(len(verdicts), 2)
        families = sorted(ln.split(":")[0][2:] for ln in verdicts)
        self.assertEqual(families, ["cpi", "employment"])


# ---------------------------------------------------------------------------
# 17-18. No provider call; no database or cache write
# ---------------------------------------------------------------------------


def _forbidden_network(*args, **kwargs):  # pragma: no cover - guard
    raise AssertionError("network call attempted during offline pipeline")


def _forbidden_sqlite(*args, **kwargs):  # pragma: no cover - guard
    raise AssertionError("sqlite connection attempted during pipeline")


class TestOfflineGuarantees(unittest.TestCase):
    def test_no_provider_or_paid_call_occurs(self):
        import socket
        with mock.patch.object(urllib.request, "urlopen",
                               _forbidden_network), \
                mock.patch.object(socket, "create_connection",
                                  _forbidden_network):
            payload = fixture_payload()
            report = r0d.render_report(payload)
        self.assertTrue(report)

    def test_no_database_or_cache_write_occurs(self):
        import sqlite3
        with mock.patch.object(sqlite3, "connect", _forbidden_sqlite):
            payload = fixture_payload()
            report = r0d.render_report(payload)
        self.assertTrue(report)

    def test_r0_modules_never_touch_the_database_layer(self):
        for module in (r0r, r0s, r0d):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertNotIn("import db", source, module.__name__)
            self.assertNotIn("sqlite", source, module.__name__)
            self.assertNotIn("events.db", source, module.__name__)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
