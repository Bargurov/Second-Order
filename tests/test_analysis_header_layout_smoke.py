"""A5A-R3 — the analysis-header layout contract validator.

The browser drive is maintainer-run (scripts/analysis_header_layout_smoke.py
serves the seeded app and validates posted measurements); the default suite
pins the VALIDATOR itself: the rules must catch the confirmed defect
geometry (a zero-width status area beside a non-shrinking control group)
and must accept the intended stacked mobile layout and the desktop layout.
No browser, network, provider, or database is touched here.
"""

import unittest

from scripts.analysis_header_layout_smoke import (
    MEASURE_JS,
    validate_layout_measurements,
)


def _m(**over):
    base = {
        "viewport_w": 375,
        "page_overflow_x": 2,
        "status_root_w": 343,
        "detail_w": 343,
        "status_right": 359,
        "container_right": 359,
        "detail_text": "Stored market data as saved — opening did not "
                       "refresh it",
        "label_text": "STALE",
    }
    base.update(over)
    return base


class TestLayoutValidator(unittest.TestCase):

    def test_the_intended_stacked_mobile_layout_passes(self):
        self.assertEqual(validate_layout_measurements(_m()), [])

    def test_the_confirmed_defect_geometry_fails(self):
        # A5A-V3/R3 finding: ~301px non-shrinking right sibling squeezed
        # the min-w-0 status column to 0px at 375px.
        errors = validate_layout_measurements(
            _m(status_root_w=0, detail_w=3))
        self.assertTrue(any("status root width" in e for e in errors))
        self.assertTrue(any("detail width" in e for e in errors))

    def test_an_escaping_status_root_fails(self):
        errors = validate_layout_measurements(
            _m(status_right=500, container_right=359))
        self.assertTrue(any("escapes its container" in e for e in errors))

    def test_new_mobile_page_overflow_fails_but_known_residual_passes(self):
        self.assertEqual(
            validate_layout_measurements(_m(page_overflow_x=4)), [])
        errors = validate_layout_measurements(_m(page_overflow_x=40))
        self.assertTrue(any("page overflow" in e for e in errors))

    def test_desktop_measurements_pass_without_mobile_overflow_rule(self):
        self.assertEqual(
            validate_layout_measurements(
                _m(viewport_w=1280, status_root_w=600, detail_w=420,
                   status_right=900, container_right=1100,
                   page_overflow_x=0)),
            [])

    def test_a_missing_state_label_fails(self):
        errors = validate_layout_measurements(_m(label_text=""))
        self.assertTrue(any("state label" in e for e in errors))

    def test_measure_snippet_targets_the_badge_row_contract(self):
        # The snippet must locate the wrappable badge row and its
        # word-wrapping detail — the two class contracts the component
        # tests pin — so the measurement and the component stay coupled.
        self.assertIn("flex.flex-wrap", MEASURE_JS)
        self.assertIn("break-words", MEASURE_JS)


if __name__ == "__main__":
    unittest.main()
