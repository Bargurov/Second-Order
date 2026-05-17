"""Tests for ``routes/demo_weekly.py``.

Pin the contract:

* Envelope carries EXACTLY these 7 top-level keys::

    ok, section, items, count, duplicate_groups_collapsed,
    warnings, errors

* ``section`` is the literal ``"weekly"``.
* Every item carries the required fields
  (``event_id`` / ``headline`` / ``event_date`` / ``duplicate_count``
  / ``grouped_event_ids`` / ``caution_label``) and surfaces the
  optional fields (``tickers`` / ``primary_ticker`` /
  ``mechanism_family``) only when the source card carried a
  non-empty value of the expected type.
* Duplicate-shaped input collapses to a single canonical item; the
  canonicalization helper's ``duplicate_count`` and
  ``grouped_event_ids`` survive into the projected item.
* Empty / missing items returns ``ok=True`` with ``count=0`` — never
  a crash.
* The module imports no DB, provider, ``yfinance``, ``market_data``,
  LLM, or FastAPI surface at module load.  No network access.
"""
from __future__ import annotations

import os
import sys
import unittest
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routes import demo_weekly as cli  # noqa: E402


_REQUIRED_ENVELOPE_KEYS = (
    "ok",
    "section",
    "items",
    "count",
    "duplicate_groups_collapsed",
    "warnings",
    "errors",
)


_REQUIRED_ITEM_KEYS = (
    "event_id",
    "headline",
    "event_date",
    "duplicate_count",
    "grouped_event_ids",
    "caution_label",
)


_OPTIONAL_ITEM_KEYS = (
    "tickers",
    "primary_ticker",
    "mechanism_family",
)


def _card(
    *,
    event_id: int,
    headline: str,
    event_date: str = "2026-04-15",
    tickers: list[str] | None = None,
    primary_ticker: str | None = None,
    mechanism_family: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "event_id":   event_id,
        "headline":   headline,
        "event_date": event_date,
    }
    if tickers is not None:
        out["tickers"] = list(tickers)
    if primary_ticker is not None:
        out["primary_ticker"] = primary_ticker
    if mechanism_family is not None:
        out["mechanism_family"] = mechanism_family
    return out


# ---------------------------------------------------------------------------
# Envelope schema
# ---------------------------------------------------------------------------


class TestEnvelopeSchema(unittest.TestCase):
    def test_top_level_keys_exact(self) -> None:
        envelope = cli.build_demo_weekly_market(items=[])
        self.assertEqual(
            set(envelope.keys()), set(_REQUIRED_ENVELOPE_KEYS),
            f"unexpected envelope keys: {sorted(envelope.keys())}",
        )

    def test_section_is_weekly(self) -> None:
        envelope = cli.build_demo_weekly_market(items=[])
        self.assertEqual(envelope["section"], "weekly")

    def test_required_item_keys_present_on_every_item(self) -> None:
        envelope = cli.build_demo_weekly_market(items=[
            _card(event_id=11, headline="OPEC extends voluntary output cuts"),
            _card(event_id=12, headline="Fed leaves policy rate unchanged"),
        ])
        self.assertEqual(envelope["count"], 2)
        for item in envelope["items"]:
            for key in _REQUIRED_ITEM_KEYS:
                self.assertIn(
                    key, item,
                    f"required key {key!r} missing from item: {item}",
                )


# ---------------------------------------------------------------------------
# Empty / missing input
# ---------------------------------------------------------------------------


class TestEmptyInput(unittest.TestCase):
    def test_empty_items_returns_ok_zero(self) -> None:
        envelope = cli.build_demo_weekly_market(items=[])
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["count"], 0)
        self.assertEqual(envelope["items"], [])
        self.assertEqual(envelope["duplicate_groups_collapsed"], 0)
        self.assertEqual(envelope["errors"], [])

    def test_default_loader_returns_empty_list_keeps_ok_true(self) -> None:
        with patch.object(
            cli, "load_weekly_market_items", return_value=[],
        ):
            envelope = cli.build_demo_weekly_market()
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["count"], 0)
        self.assertEqual(envelope["items"], [])

    def test_loader_exception_surfaces_as_error_not_crash(self) -> None:
        def boom(*, limit: int) -> list[dict[str, Any]]:
            raise RuntimeError("simulated weekly cache failure")

        envelope = cli.build_demo_weekly_market(loader=boom)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["count"], 0)
        self.assertTrue(
            any("weekly_market_load_failed" in e for e in envelope["errors"]),
            f"errors: {envelope['errors']}",
        )

    def test_non_list_loader_return_is_handled(self) -> None:
        def returns_dict(*, limit: int) -> Any:
            return {"not": "a list"}  # type: ignore[return-value]

        envelope = cli.build_demo_weekly_market(loader=returns_dict)
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["count"], 0)
        self.assertTrue(
            any("non-list" in w for w in envelope["warnings"]),
            f"warnings: {envelope['warnings']}",
        )


# ---------------------------------------------------------------------------
# Canonicalization — duplicates collapse, singletons pass through
# ---------------------------------------------------------------------------


class TestCanonicalization(unittest.TestCase):
    def test_duplicate_shaped_input_collapses_to_single_item(self) -> None:
        items = [
            _card(event_id=100, headline="OPEC extends voluntary oil output cuts"),
            _card(event_id=101, headline="OPEC extends voluntary oil output cuts"),
            _card(event_id=102, headline="OPEC extends voluntary oil output cuts"),
        ]
        envelope = cli.build_demo_weekly_market(items=items)
        self.assertEqual(envelope["count"], 1)
        self.assertEqual(envelope["duplicate_groups_collapsed"], 1)
        only = envelope["items"][0]
        self.assertEqual(only["duplicate_count"], 2)
        self.assertEqual(only["grouped_event_ids"], [100, 101, 102])

    def test_singleton_passes_through_with_default_metadata(self) -> None:
        envelope = cli.build_demo_weekly_market(items=[
            _card(event_id=200, headline="Fed leaves policy rate unchanged"),
        ])
        self.assertEqual(envelope["count"], 1)
        self.assertEqual(envelope["duplicate_groups_collapsed"], 0)
        only = envelope["items"][0]
        self.assertEqual(only["duplicate_count"], 0)
        # Singleton items still surface ``grouped_event_ids`` so
        # downstream consumers can iterate uniformly.
        self.assertEqual(only["grouped_event_ids"], [200])

    def test_mixed_duplicates_and_singletons(self) -> None:
        items = [
            _card(event_id=300, headline="Story A"),
            _card(event_id=301, headline="Story A"),
            _card(event_id=302, headline="Story B"),
        ]
        envelope = cli.build_demo_weekly_market(items=items)
        self.assertEqual(envelope["count"], 2)
        self.assertEqual(envelope["duplicate_groups_collapsed"], 1)
        canonical_a = next(
            i for i in envelope["items"] if "A" in i["headline"]
        )
        singleton_b = next(
            i for i in envelope["items"] if "B" in i["headline"]
        )
        self.assertEqual(canonical_a["duplicate_count"], 1)
        self.assertEqual(canonical_a["grouped_event_ids"], [300, 301])
        self.assertEqual(singleton_b["duplicate_count"], 0)
        self.assertEqual(singleton_b["grouped_event_ids"], [302])


# ---------------------------------------------------------------------------
# Optional fields — included only when source provides them
# ---------------------------------------------------------------------------


class TestOptionalFields(unittest.TestCase):
    def test_tickers_included_when_present(self) -> None:
        envelope = cli.build_demo_weekly_market(items=[
            _card(
                event_id=400, headline="Energy headline",
                tickers=["XLE", "XOM"],
            ),
        ])
        item = envelope["items"][0]
        self.assertEqual(item["tickers"], ["XLE", "XOM"])

    def test_primary_ticker_included_when_present(self) -> None:
        envelope = cli.build_demo_weekly_market(items=[
            _card(
                event_id=401, headline="Primary ticker headline",
                primary_ticker="XLE",
            ),
        ])
        item = envelope["items"][0]
        self.assertEqual(item["primary_ticker"], "XLE")

    def test_mechanism_family_included_when_present(self) -> None:
        envelope = cli.build_demo_weekly_market(items=[
            _card(
                event_id=402, headline="Mechanism headline",
                mechanism_family="supply_shock",
            ),
        ])
        item = envelope["items"][0]
        self.assertEqual(item["mechanism_family"], "supply_shock")

    def test_optional_fields_omitted_when_absent(self) -> None:
        envelope = cli.build_demo_weekly_market(items=[
            _card(event_id=403, headline="Minimal headline"),
        ])
        item = envelope["items"][0]
        for key in _OPTIONAL_ITEM_KEYS:
            self.assertNotIn(
                key, item,
                f"optional key {key!r} should be absent: {item}",
            )

    def test_empty_tickers_list_is_omitted(self) -> None:
        envelope = cli.build_demo_weekly_market(items=[
            _card(event_id=404, headline="Empty tickers", tickers=[]),
        ])
        item = envelope["items"][0]
        self.assertNotIn("tickers", item)


# ---------------------------------------------------------------------------
# Caution label
# ---------------------------------------------------------------------------


class TestCautionLabel(unittest.TestCase):
    def test_caution_label_present_on_every_item(self) -> None:
        envelope = cli.build_demo_weekly_market(items=[
            _card(event_id=500, headline="Headline 1"),
            _card(event_id=501, headline="Headline 2"),
        ])
        for item in envelope["items"]:
            self.assertIn("caution_label", item)
            self.assertIsInstance(item["caution_label"], str)
            self.assertTrue(item["caution_label"])

    def test_caution_label_is_the_module_constant(self) -> None:
        envelope = cli.build_demo_weekly_market(items=[
            _card(event_id=502, headline="Headline"),
        ])
        self.assertEqual(envelope["items"][0]["caution_label"], cli.CAUTION_LABEL)


# ---------------------------------------------------------------------------
# Defensive — non-dict entries, missing event_id
# ---------------------------------------------------------------------------


class TestDefensive(unittest.TestCase):
    def test_non_dict_entries_are_dropped_with_warning(self) -> None:
        envelope = cli.build_demo_weekly_market(items=[
            _card(event_id=600, headline="Good card"),
            "not a dict",  # type: ignore[list-item]
            None,          # type: ignore[list-item]
        ])
        self.assertEqual(envelope["count"], 1)
        self.assertTrue(
            any("non-dict" in w for w in envelope["warnings"]),
            f"warnings: {envelope['warnings']}",
        )

    def test_card_without_event_id_yields_empty_grouped_event_ids(self) -> None:
        envelope = cli.build_demo_weekly_market(items=[
            {"headline": "No event_id"},
        ])
        item = envelope["items"][0]
        self.assertIsNone(item["event_id"])
        self.assertEqual(item["grouped_event_ids"], [])
        self.assertEqual(item["duplicate_count"], 0)

    def test_non_int_event_id_is_normalised_to_none(self) -> None:
        envelope = cli.build_demo_weekly_market(items=[
            {"event_id": "not-an-int", "headline": "Bad event_id"},
        ])
        item = envelope["items"][0]
        self.assertIsNone(item["event_id"])


# ---------------------------------------------------------------------------
# Loader seam
# ---------------------------------------------------------------------------


class TestLoaderSeam(unittest.TestCase):
    def test_loader_supplied_items_are_passed_through(self) -> None:
        seen: dict[str, Any] = {}

        def fake_loader(*, limit: int) -> list[dict[str, Any]]:
            seen["limit"] = limit
            return [
                _card(event_id=700, headline="Loaded card"),
            ]

        envelope = cli.build_demo_weekly_market(loader=fake_loader, limit=7)
        self.assertEqual(seen["limit"], 7)
        self.assertEqual(envelope["count"], 1)
        self.assertEqual(envelope["items"][0]["event_id"], 700)

    def test_explicit_items_bypasses_loader(self) -> None:
        def must_not_be_called(*, limit: int) -> list[dict[str, Any]]:
            raise AssertionError("loader was called despite explicit items")

        envelope = cli.build_demo_weekly_market(
            items=[_card(event_id=701, headline="Explicit")],
            loader=must_not_be_called,
        )
        self.assertEqual(envelope["count"], 1)


# ---------------------------------------------------------------------------
# Import isolation — no DB / provider / LLM / FastAPI at module load
# ---------------------------------------------------------------------------


class TestImportIsolation(unittest.TestCase):
    _BLOCKED = (
        "yfinance",
        "fastapi",
        "api",
        "market_data",
        "movers_cache",   # the lazy loader must NOT pull this in at import
    )

    def test_module_import_does_not_pull_provider_fastapi_or_cache(self) -> None:
        from tests._import_isolation_check import (
            assert_module_import_does_not_leak,
        )
        assert_module_import_does_not_leak(
            self,
            module_name="routes.demo_weekly",
            blocked=self._BLOCKED,
            # The default ``blocked_starts_with=("routes.",)`` is meant
            # for scripts that should NOT pull any route module in; it
            # is the wrong guard for a route module testing its own
            # import surface.  Override with an empty tuple so the
            # legitimate ``routes.weekly_canonicalization`` import does
            # not register as a leak.
            blocked_starts_with=(),
        )


if __name__ == "__main__":
    unittest.main()
