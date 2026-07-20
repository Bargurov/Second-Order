"""R0 normalized release-record contract tests (r0-release-register-v1).

Point-in-time discipline by construction: every numeric fixture below is a
real captured value from the selected zero-cost sources (ALFRED vintage
matrices for CPIAUCSL / PAYEMS; BLS schedule-archive snapshot rows via
pinned Wayback captures), never an invented parallel shape.  No network
call, no database, no cache write occurs anywhere in this module: the
contract layer is pure normalization.

Captured source facts used as fixtures:

* CPI (CPIAUCSL, SA index): vintage 2024-02-13 (Jan-2024 release) shows
  2023-12 = 308.742 and 2024-01 = 309.685; vintage 2024-03-12 (Feb-2024
  release) shows 2024-01 = 309.685 (unrevised) and 2024-02 = 311.054.
  Schedule row (Wayback snapshot 20240427220534 of
  bls.gov/schedule/news_release/cpi.htm): February 2024 -> Mar. 12, 2024,
  08:30 AM.
* Employment (PAYEMS, SA level, thousands): vintage 2024-11-01 (Oct-2024
  release) shows 2024-09 = 158993 and 2024-10 = 159005; vintage
  2024-12-06 (Nov-2024 release) shows 2024-10 = 159061 (a real upward
  revision of +56) and 2024-11 = 159288.  Schedule rows (Wayback snapshot
  of bls.gov/schedule/news_release/empsit.htm): October 2024 -> Nov. 01,
  2024, 08:30 AM; November 2024 -> Dec. 06, 2024, 08:30 AM.
"""

from __future__ import annotations

import copy
import json
import math
import unittest

from scripts import r0_release_register as r0r


# ---------------------------------------------------------------------------
# Real captured fixture atoms
# ---------------------------------------------------------------------------

CPI_SA = {"series_id": "CPIAUCSL"}
PAYEMS = {"series_id": "PAYEMS"}


def series_meta(series_id: str) -> dict:
    for family in r0r.FAMILIES:
        for s in r0r.SERIES[family]:
            if s["series_id"] == series_id:
                return s
    raise AssertionError(f"series {series_id} not registered")


def cpi_schedule_entry(**overrides) -> dict:
    entry = {
        "reference_period": "2024-02",
        "release_date": "2024-03-12",
        "release_time_local": "08:30",
        "source_snapshots": ["wayback:20240427220534"],
        "schedule_conflicts": [],
    }
    entry.update(overrides)
    return entry


def employment_schedule_entry(**overrides) -> dict:
    entry = {
        "reference_period": "2024-11",
        "release_date": "2024-12-06",
        "release_time_local": "08:30",
        "source_snapshots": ["wayback:20241231"],
        "schedule_conflicts": [],
    }
    entry.update(overrides)
    return entry


def cell(series_id: str, **overrides) -> dict:
    meta = series_meta(series_id)
    base = {
        "value": None,
        "status": "available",
        "unit": meta["unit"],
        "seasonal_adjustment": meta["seasonal_adjustment"],
        "measure_kind": meta["measure_kind"],
        "vintage_date": None,
        "reason": None,
    }
    base.update(overrides)
    return r0r.value_cell(**base)


def cpi_cells() -> dict:
    """Feb-2024 CPI release (2024-03-12) cells from the captured vintages."""
    return {
        "actual": cell("CPIAUCSL", value=311.054, vintage_date="2024-03-12"),
        "prior": cell("CPIAUCSL", value=309.685, vintage_date="2024-02-13"),
        "revised_prior": cell(
            "CPIAUCSL", value=309.685, vintage_date="2024-03-12"),
        "consensus": cell(
            "CPIAUCSL", status="source_unavailable",
            reason="no zero-cost reproducible point-in-time consensus "
                   "source (see consensus source survey)"),
    }


def employment_cells() -> dict:
    """Nov-2024 Employment Situation release (2024-12-06) PAYEMS cells."""
    return {
        "actual": cell("PAYEMS", value=159288.0, vintage_date="2024-12-06"),
        "prior": cell("PAYEMS", value=159005.0, vintage_date="2024-11-01"),
        "revised_prior": cell(
            "PAYEMS", value=159061.0, vintage_date="2024-12-06"),
        "consensus": cell(
            "PAYEMS", status="source_unavailable",
            reason="no zero-cost reproducible point-in-time consensus "
                   "source (see consensus source survey)"),
    }


def normalize_cpi(**overrides):
    kwargs = dict(
        family="cpi",
        series=series_meta("CPIAUCSL"),
        schedule_entry=cpi_schedule_entry(),
        source_reference={
            "schedule": "bls.gov/schedule/news_release/cpi.htm via pinned "
                        "Wayback snapshot 20240427220534",
            "values": "ALFRED vintage API series CPIAUCSL",
        },
        source_timestamp="2026-07-20T00:00:00+00:00",
        retrieval_method="bls_schedule_archive_snapshot+alfred_vintage_api",
        **cpi_cells(),
    )
    kwargs.update(overrides)
    return r0r.normalize_release(**kwargs)


def normalize_employment(**overrides):
    kwargs = dict(
        family="employment",
        series=series_meta("PAYEMS"),
        schedule_entry=employment_schedule_entry(),
        source_reference={
            "schedule": "bls.gov/schedule/news_release/empsit.htm via "
                        "pinned Wayback snapshots",
            "values": "ALFRED vintage API series PAYEMS",
        },
        source_timestamp="2026-07-20T00:00:00+00:00",
        retrieval_method="bls_schedule_archive_snapshot+alfred_vintage_api",
        **employment_cells(),
    )
    kwargs.update(overrides)
    return r0r.normalize_release(**kwargs)


# ---------------------------------------------------------------------------
# Frozen vocabulary
# ---------------------------------------------------------------------------


class TestFrozenVocabulary(unittest.TestCase):
    def test_contract_id(self):
        self.assertEqual(r0r.R0_CONTRACT, "r0-release-register-v1")

    def test_families_exact(self):
        self.assertEqual(r0r.FAMILIES, ("cpi", "employment"))

    def test_series_registry_exact(self):
        got = {f: tuple(s["series_id"] for s in r0r.SERIES[f])
               for f in r0r.FAMILIES}
        self.assertEqual(got, {"cpi": ("CPIAUCSL", "CPIAUCNS"),
                               "employment": ("PAYEMS", "UNRATE")})

    def test_availability_states_exact(self):
        self.assertEqual(r0r.AVAILABILITY_STATES, (
            "available", "missing_consensus", "missing_prior",
            "missing_actual", "timestamp_unresolved", "unit_incompatible",
            "revision_ambiguous", "source_unavailable", "not_applicable"))

    def test_seasonal_bases_distinct(self):
        sa = series_meta("CPIAUCSL")["seasonal_adjustment"]
        nsa = series_meta("CPIAUCNS")["seasonal_adjustment"]
        self.assertEqual((sa, nsa), ("SA", "NSA"))


# ---------------------------------------------------------------------------
# 1-2. Valid normalization (one real release per family)
# ---------------------------------------------------------------------------


class TestValidNormalization(unittest.TestCase):
    def test_valid_cpi_record(self):
        rec = normalize_cpi()
        self.assertEqual(rec["contract"], "r0-release-register-v1")
        self.assertEqual(rec["release_id"], "cpi:2024-03-12")
        self.assertEqual(rec["family"], "cpi")
        self.assertEqual(rec["release_name"], "Consumer Price Index")
        self.assertEqual(rec["series_id"], "CPIAUCSL")
        self.assertEqual(rec["reference_period"], "2024-02")
        # 2024-03-12 is inside US daylight-saving time: offset must be -04:00
        self.assertEqual(rec["scheduled_timestamp"],
                         "2024-03-12T08:30:00-04:00")
        self.assertEqual(rec["actual"]["value"], 311.054)
        self.assertEqual(rec["actual"]["vintage_date"], "2024-03-12")
        self.assertEqual(rec["prior"]["value"], 309.685)
        self.assertEqual(rec["prior"]["vintage_date"], "2024-02-13")
        self.assertEqual(rec["revised_prior"]["value"], 309.685)
        self.assertIsNone(rec["consensus"]["value"])
        self.assertEqual(rec["unit"], "index_1982_1984_100")
        self.assertEqual(rec["seasonal_adjustment"], "SA")
        self.assertEqual(rec["frequency"], "monthly")
        self.assertEqual(rec["revision_status"], "prior_unrevised")
        self.assertEqual(rec["availability_status"], "missing_consensus")
        self.assertIn("consensus", rec["missing_reason"])
        self.assertEqual(
            rec["retrieval_method"],
            "bls_schedule_archive_snapshot+alfred_vintage_api")
        self.assertTrue(rec["source_reference"]["values"])
        self.assertTrue(rec["source_timestamp"])

    def test_valid_employment_record(self):
        rec = normalize_employment()
        self.assertEqual(rec["release_id"], "employment:2024-12-06")
        self.assertEqual(rec["release_name"], "Employment Situation")
        self.assertEqual(rec["series_id"], "PAYEMS")
        # 2024-12-06 is standard time: offset must be -05:00
        self.assertEqual(rec["scheduled_timestamp"],
                         "2024-12-06T08:30:00-05:00")
        self.assertEqual(rec["actual"]["value"], 159288.0)
        self.assertEqual(rec["prior"]["value"], 159005.0)
        self.assertEqual(rec["revised_prior"]["value"], 159061.0)
        self.assertEqual(rec["unit"], "thousands_of_persons")
        self.assertEqual(rec["revision_status"], "prior_revised")
        self.assertEqual(rec["availability_status"], "missing_consensus")


# ---------------------------------------------------------------------------
# 3-4. Field identity: distinctness and revision preservation
# ---------------------------------------------------------------------------


class TestFieldIdentity(unittest.TestCase):
    def test_actual_prior_consensus_remain_distinct(self):
        cells = cpi_cells()
        rec = normalize_cpi()
        self.assertNotEqual(rec["actual"]["value"], rec["prior"]["value"])
        self.assertEqual(rec["consensus"]["status"], "source_unavailable")
        # the record must hold copies, not aliases of the input cells
        self.assertIsNot(rec["actual"], cells["actual"])
        cells2 = cpi_cells()
        rec2 = normalize_cpi(**cells2)
        cells2["actual"]["value"] = -1.0
        self.assertEqual(rec2["actual"]["value"], 311.054)

    def test_revised_prior_never_overwrites_original_prior(self):
        rec = normalize_employment()
        # Real revision: original 159005 (vintage 2024-11-01) stays intact
        # while the release-day vintage shows 159061.
        self.assertEqual(rec["prior"]["value"], 159005.0)
        self.assertEqual(rec["prior"]["vintage_date"], "2024-11-01")
        self.assertEqual(rec["revised_prior"]["value"], 159061.0)
        self.assertEqual(rec["revised_prior"]["vintage_date"], "2024-12-06")
        self.assertEqual(rec["revision_status"], "prior_revised")


# ---------------------------------------------------------------------------
# 5-7. Unit / kind / seasonal-basis incompatibility fails closed
# ---------------------------------------------------------------------------


class TestUnitDiscipline(unittest.TestCase):
    def assert_unit_incompatible(self, rec):
        self.assertEqual(rec["availability_status"], "unit_incompatible")
        for field in ("actual", "prior", "revised_prior"):
            self.assertIsNone(rec[field]["value"])
            self.assertEqual(rec[field]["status"], "unit_incompatible")
        self.assertTrue(rec["missing_reason"])

    def test_units_cannot_be_silently_mixed(self):
        cells = cpi_cells()
        cells["prior"] = cell("CPIAUCSL", value=309.685,
                              vintage_date="2024-02-13",
                              unit="percent_of_labor_force")
        rec = normalize_cpi(**cells)
        self.assert_unit_incompatible(rec)
        self.assertIn("percent_of_labor_force", rec["missing_reason"])
        self.assertIn("index_1982_1984_100", rec["missing_reason"])

    def test_level_and_monthly_change_cannot_be_mixed(self):
        cells = cpi_cells()
        cells["prior"] = cell("CPIAUCSL", value=0.4,
                              vintage_date="2024-02-13",
                              measure_kind="monthly_percent_change")
        rec = normalize_cpi(**cells)
        self.assert_unit_incompatible(rec)

    def test_sa_and_nsa_cannot_be_mixed(self):
        cells = cpi_cells()
        cells["prior"] = cell("CPIAUCSL", value=308.417,
                              vintage_date="2024-02-13",
                              seasonal_adjustment="NSA")
        rec = normalize_cpi(**cells)
        self.assert_unit_incompatible(rec)


# ---------------------------------------------------------------------------
# 8. Ambiguous release timestamp fails closed
# ---------------------------------------------------------------------------


class TestTimestampDiscipline(unittest.TestCase):
    def test_missing_release_time_fails_closed(self):
        rec = normalize_cpi(
            schedule_entry=cpi_schedule_entry(release_time_local=None))
        self.assertEqual(rec["availability_status"], "timestamp_unresolved")
        self.assertIsNone(rec["scheduled_timestamp"])
        self.assertIn("time", rec["missing_reason"])

    def test_unparseable_release_time_fails_closed(self):
        rec = normalize_cpi(
            schedule_entry=cpi_schedule_entry(release_time_local="morning"))
        self.assertEqual(rec["availability_status"], "timestamp_unresolved")
        self.assertIsNone(rec["scheduled_timestamp"])

    def test_conflicting_schedule_attestations_fail_closed(self):
        conflict = [{"snapshot": "wayback:20250101", "release_date":
                     "2024-03-13", "release_time_local": "08:30"}]
        rec = normalize_cpi(
            schedule_entry=cpi_schedule_entry(schedule_conflicts=conflict))
        self.assertEqual(rec["availability_status"], "timestamp_unresolved")
        self.assertIsNone(rec["scheduled_timestamp"])
        self.assertIn("2024-03-13", rec["missing_reason"])

    def test_invalid_release_date_is_an_identity_error(self):
        with self.assertRaises(ValueError):
            normalize_cpi(
                schedule_entry=cpi_schedule_entry(release_date="2024-03-99"))


# ---------------------------------------------------------------------------
# 9-10. Missing consensus / prior stay explicitly missing
# ---------------------------------------------------------------------------


class TestExplicitMissingness(unittest.TestCase):
    def test_missing_consensus_remains_explicitly_missing(self):
        rec = normalize_cpi()
        self.assertIsNone(rec["consensus"]["value"])
        self.assertEqual(rec["consensus"]["status"], "source_unavailable")
        self.assertIn("consensus", rec["missing_reason"])
        self.assertEqual(rec["availability_status"], "missing_consensus")

    def test_missing_prior_remains_explicitly_missing(self):
        cells = cpi_cells()
        cells["prior"] = cell(
            "CPIAUCSL", status="missing",
            reason="no vintage before the release date contains the "
                   "previous reference month")
        rec = normalize_cpi(**cells)
        self.assertIsNone(rec["prior"]["value"])
        self.assertEqual(rec["prior"]["status"], "missing")
        # missing_prior outranks missing_consensus in the fixed precedence
        self.assertEqual(rec["availability_status"], "missing_prior")
        self.assertIn("prior", rec["missing_reason"])
        self.assertIn("consensus", rec["missing_reason"])

    def test_missing_actual_outranks_other_missing_fields(self):
        cells = cpi_cells()
        cells["actual"] = cell("CPIAUCSL", status="missing",
                               reason="no vintage on the release date")
        rec = normalize_cpi(**cells)
        self.assertEqual(rec["availability_status"], "missing_actual")


# ---------------------------------------------------------------------------
# 11. Malformed numeric values fail closed
# ---------------------------------------------------------------------------


class TestNumericDiscipline(unittest.TestCase):
    def test_string_number_fails_closed(self):
        with self.assertRaises(ValueError):
            cell("CPIAUCSL", value="311.054", vintage_date="2024-03-12")

    def test_nan_fails_closed(self):
        with self.assertRaises(ValueError):
            cell("CPIAUCSL", value=math.nan, vintage_date="2024-03-12")

    def test_infinity_fails_closed(self):
        with self.assertRaises(ValueError):
            cell("CPIAUCSL", value=math.inf, vintage_date="2024-03-12")

    def test_boolean_fails_closed(self):
        with self.assertRaises(ValueError):
            cell("CPIAUCSL", value=True, vintage_date="2024-03-12")

    def test_available_cell_requires_a_value(self):
        with self.assertRaises(ValueError):
            cell("CPIAUCSL", value=None, vintage_date="2024-03-12")

    def test_missing_cell_requires_a_reason_and_no_value(self):
        with self.assertRaises(ValueError):
            cell("CPIAUCSL", status="missing", reason=None)
        with self.assertRaises(ValueError):
            cell("CPIAUCSL", status="missing", value=1.0, reason="x")


# ---------------------------------------------------------------------------
# 12. Duplicate release identities fail closed
# ---------------------------------------------------------------------------


class TestRegisterIdentity(unittest.TestCase):
    def test_duplicate_release_ids_fail_closed(self):
        rec = normalize_cpi()
        with self.assertRaises(ValueError):
            r0r.build_register([rec, copy.deepcopy(rec)])

    def test_same_reference_period_twice_fails_closed(self):
        first = normalize_cpi()
        entry = cpi_schedule_entry(release_date="2024-03-13")
        cells = cpi_cells()
        cells["actual"] = cell("CPIAUCSL", value=311.054,
                               vintage_date="2024-03-13")
        cells["prior"] = cell("CPIAUCSL", value=309.685,
                              vintage_date="2024-02-13")
        cells["revised_prior"] = cell("CPIAUCSL", value=309.685,
                                      vintage_date="2024-03-13")
        second = normalize_cpi(schedule_entry=entry, **cells)
        with self.assertRaises(ValueError):
            r0r.build_register([first, second])


# ---------------------------------------------------------------------------
# 13. Reference-period validity
# ---------------------------------------------------------------------------


class TestReferencePeriod(unittest.TestCase):
    def test_invalid_month_fails(self):
        with self.assertRaises(ValueError):
            normalize_cpi(
                schedule_entry=cpi_schedule_entry(reference_period="2024-13"))

    def test_malformed_period_fails(self):
        with self.assertRaises(ValueError):
            normalize_cpi(
                schedule_entry=cpi_schedule_entry(reference_period="202402"))

    def test_reference_period_must_precede_release_date(self):
        # the reference month must be fully elapsed before the release
        with self.assertRaises(ValueError):
            normalize_cpi(
                schedule_entry=cpi_schedule_entry(reference_period="2024-03"))
        with self.assertRaises(ValueError):
            normalize_cpi(
                schedule_entry=cpi_schedule_entry(reference_period="2024-04"))


# ---------------------------------------------------------------------------
# 14. Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering(unittest.TestCase):
    def test_register_order_is_publication_order(self):
        cpi = normalize_cpi()
        emp = normalize_employment()
        entry = employment_schedule_entry(
            reference_period="2024-10", release_date="2024-11-01")
        cells = {
            "actual": cell("PAYEMS", value=159005.0,
                           vintage_date="2024-11-01"),
            "prior": cell("PAYEMS", value=158993.0,
                          vintage_date="2024-10-04"),
            "revised_prior": cell("PAYEMS", value=158993.0,
                                  vintage_date="2024-11-01"),
            "consensus": cell("PAYEMS", status="source_unavailable",
                              reason="no zero-cost reproducible "
                                     "point-in-time consensus source"),
        }
        emp_oct = normalize_employment(schedule_entry=entry, **cells)
        for permutation in ([cpi, emp, emp_oct], [emp_oct, emp, cpi],
                            [emp, cpi, emp_oct]):
            register = r0r.build_register(permutation)
            got = [(r["release_id"], r["series_id"]) for r in register]
            self.assertEqual(got, [
                ("cpi:2024-03-12", "CPIAUCSL"),
                ("employment:2024-11-01", "PAYEMS"),
                ("employment:2024-12-06", "PAYEMS"),
            ])


# ---------------------------------------------------------------------------
# 15. No future revision may populate a point-in-time field
# ---------------------------------------------------------------------------


class TestPointInTimeGuards(unittest.TestCase):
    def test_actual_from_future_vintage_fails(self):
        cells = cpi_cells()
        cells["actual"] = cell("CPIAUCSL", value=313.207,
                               vintage_date="2024-04-10")
        with self.assertRaises(ValueError):
            normalize_cpi(**cells)

    def test_revised_prior_from_future_vintage_fails(self):
        cells = cpi_cells()
        cells["revised_prior"] = cell("CPIAUCSL", value=309.685,
                                      vintage_date="2024-04-10")
        with self.assertRaises(ValueError):
            normalize_cpi(**cells)

    def test_prior_must_come_from_a_strictly_earlier_vintage(self):
        cells = cpi_cells()
        cells["prior"] = cell("CPIAUCSL", value=309.685,
                              vintage_date="2024-03-12")
        with self.assertRaises(ValueError):
            normalize_cpi(**cells)
        cells["prior"] = cell("CPIAUCSL", value=309.685,
                              vintage_date="2024-04-10")
        with self.assertRaises(ValueError):
            normalize_cpi(**cells)

    def test_available_cell_requires_vintage_provenance(self):
        cells = cpi_cells()
        cells["actual"] = cell("CPIAUCSL", value=311.054,
                               vintage_date="2024-03-11")
        # an "actual" whose vintage is not the release-day vintage is not
        # the as-published print; the normalizer must refuse it
        with self.assertRaises(ValueError):
            normalize_cpi(**cells)


# ---------------------------------------------------------------------------
# 16. Repeated normalization is deterministic
# ---------------------------------------------------------------------------


class TestDeterminism(unittest.TestCase):
    def test_repeated_normalization_is_identical(self):
        a = normalize_cpi()
        b = normalize_cpi()
        self.assertEqual(a, b)
        self.assertEqual(r0r.canonical_json(a), r0r.canonical_json(b))

    def test_register_canonical_json_is_stable(self):
        one = r0r.canonical_json(
            r0r.build_register([normalize_cpi(), normalize_employment()]))
        two = r0r.canonical_json(
            r0r.build_register([normalize_employment(), normalize_cpi()]))
        self.assertEqual(one, two)
        # canonical form is loadable and round-trips
        self.assertEqual(json.loads(one), json.loads(two))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
