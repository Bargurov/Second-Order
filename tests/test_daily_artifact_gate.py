"""Tests for ``routes/daily_artifact_gate.py``.

The Daily Section C artifact gate refuses to promote an inbox-derived
mover card unless a reviewed ``analyzed_event_artifact_<cid>.json``
exists on disk under the configured ``artifact_dir`` and carries the
three artifact-backed fields the planner pins.  See
``scripts/section_c_daily_artifact_gate_plan.py`` for the design.

Read-only contract:

* The gate never writes the artifact, never mutates the card, and
  never enriches fields.  No DB, ``yfinance``, ``market_data``, LLM,
  paid provider, or FastAPI surface is imported at module load.
* Weekly canonicalization (``routes/weekly_canonicalization.py``) is
  not touched.
* Still Moving's persistent gate (``is_high_conviction_persistent``
  in ``mover_card_normalizer.py``) is not touched.

What the tests pin:

* A card whose ``candidate_id`` points at a present, well-formed
  artifact carrying the three required fields is admitted.
* A card without ``candidate_id``, with a missing artifact file,
  with a missing required field, or with ``mechanism_family ==
  "none"`` is held for review.
* ``filter_daily_section_c_cards`` returns the admitted list and a
  meta dict containing the gate id and held/admitted counts.
* ``routes/movers.py`` imports the gate, invokes it on the Daily
  branch only, surfaces the held count under
  ``envelope.meta.daily_artifact_gate``, and does not touch the
  weekly or persistent route bodies.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routes import daily_artifact_gate as gate  # noqa: E402


def _load_movers_function(name: str) -> Callable:
    """Extract a free-standing function from ``routes/movers.py`` and
    exec it in an isolated namespace.

    Importing ``routes.movers`` from a test triggers the FastAPI /
    ``api`` import cascade the gate test file is required to avoid.
    The helper under test is a small read-only function with no
    cross-module dependencies, so AST-extracting it keeps the test
    behavioral without paying the heavy import cost.
    """
    src = (
        Path(__file__).resolve().parents[1] / "routes" / "movers.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            module = ast.Module(body=[node], type_ignores=[])
            ns: dict = {}
            exec(compile(module, "routes/movers.py", "exec"), ns)
            return ns[name]
    raise AssertionError(
        f"function {name} not found at module scope in routes/movers.py"
    )


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


_GATE_ID = "daily_section_c_requires_analyzed_event_artifact"


def _write_artifact(
    artifact_dir: Path,
    *,
    candidate_id: str,
    mechanism_family: str | None = "supply_shock",
    primary_ticker:   str | None = "XOM",
    benchmark_ticker: str | None = "XLE",
    extra:            dict[str, Any] | None = None,
) -> Path:
    body: dict[str, Any] = {}
    if mechanism_family is not None:
        body["mechanism_family"] = mechanism_family
    if primary_ticker is not None:
        body["primary_ticker"] = primary_ticker
    if benchmark_ticker is not None:
        body["benchmark_ticker"] = benchmark_ticker
    if extra:
        body.update(extra)
    path = artifact_dir / f"analyzed_event_artifact_{candidate_id}.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _card(
    *,
    candidate_id: str | None = "cid-001",
    headline: str = "OPEC extends voluntary cuts",
    mechanism_family: str | None = "supply_shock",
) -> dict[str, Any]:
    card: dict[str, Any] = {"headline": headline}
    if candidate_id is not None:
        card["candidate_id"] = candidate_id
    if mechanism_family is not None:
        card["mechanism_family"] = mechanism_family
    return card


# ---------------------------------------------------------------------------
# Predicate behavior
# ---------------------------------------------------------------------------


class TestIsArtifactBackedDailyCard(unittest.TestCase):

    def test_admits_when_artifact_present_with_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_artifact(artifact_dir, candidate_id="cid-1")
            self.assertTrue(
                gate.is_artifact_backed_daily_card(
                    _card(candidate_id="cid-1"),
                    artifact_dir=artifact_dir,
                )
            )

    def test_holds_when_artifact_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(
                gate.is_artifact_backed_daily_card(
                    _card(candidate_id="cid-missing"),
                    artifact_dir=Path(tmp),
                )
            )

    def test_holds_when_candidate_id_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(
                gate.is_artifact_backed_daily_card(
                    _card(candidate_id=None),
                    artifact_dir=Path(tmp),
                )
            )

    def test_holds_when_candidate_id_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(
                gate.is_artifact_backed_daily_card(
                    {"candidate_id": "   "},
                    artifact_dir=Path(tmp),
                )
            )

    def test_holds_when_mechanism_family_missing_on_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_artifact(
                artifact_dir, candidate_id="cid-2",
                mechanism_family=None,
            )
            self.assertFalse(
                gate.is_artifact_backed_daily_card(
                    _card(candidate_id="cid-2"),
                    artifact_dir=artifact_dir,
                )
            )

    def test_holds_when_mechanism_family_is_none_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_artifact(
                artifact_dir, candidate_id="cid-3",
                mechanism_family="none",
            )
            self.assertFalse(
                gate.is_artifact_backed_daily_card(
                    _card(candidate_id="cid-3"),
                    artifact_dir=artifact_dir,
                )
            )

    def test_holds_when_primary_ticker_missing_on_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_artifact(
                artifact_dir, candidate_id="cid-4",
                primary_ticker=None,
            )
            self.assertFalse(
                gate.is_artifact_backed_daily_card(
                    _card(candidate_id="cid-4"),
                    artifact_dir=artifact_dir,
                )
            )

    def test_holds_when_benchmark_ticker_missing_on_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_artifact(
                artifact_dir, candidate_id="cid-5",
                benchmark_ticker=None,
            )
            self.assertFalse(
                gate.is_artifact_backed_daily_card(
                    _card(candidate_id="cid-5"),
                    artifact_dir=artifact_dir,
                )
            )

    def test_holds_when_required_field_is_blank_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_artifact(
                artifact_dir, candidate_id="cid-6",
                primary_ticker="   ",
            )
            self.assertFalse(
                gate.is_artifact_backed_daily_card(
                    _card(candidate_id="cid-6"),
                    artifact_dir=artifact_dir,
                )
            )

    def test_holds_when_artifact_is_not_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            (artifact_dir / "analyzed_event_artifact_cid-7.json").write_text(
                "not json {", encoding="utf-8",
            )
            self.assertFalse(
                gate.is_artifact_backed_daily_card(
                    _card(candidate_id="cid-7"),
                    artifact_dir=artifact_dir,
                )
            )

    def test_holds_when_artifact_root_is_not_a_json_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            (artifact_dir / "analyzed_event_artifact_cid-8.json").write_text(
                "[]", encoding="utf-8",
            )
            self.assertFalse(
                gate.is_artifact_backed_daily_card(
                    _card(candidate_id="cid-8"),
                    artifact_dir=artifact_dir,
                )
            )

    def test_holds_for_non_dict_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(
                gate.is_artifact_backed_daily_card(
                    None, artifact_dir=Path(tmp),
                )
            )
            self.assertFalse(
                gate.is_artifact_backed_daily_card(
                    "not a card", artifact_dir=Path(tmp),
                )
            )

    def test_predicate_does_not_mutate_card_or_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            artifact_path = _write_artifact(
                artifact_dir, candidate_id="cid-9",
            )
            original_artifact = artifact_path.read_bytes()
            card = _card(candidate_id="cid-9")
            original_card = dict(card)
            gate.is_artifact_backed_daily_card(card, artifact_dir=artifact_dir)
            self.assertEqual(card, original_card)
            self.assertEqual(artifact_path.read_bytes(), original_artifact)

    def test_predicate_does_not_create_artifact_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_dir = Path(tmp) / "does_not_exist"
            self.assertFalse(missing_dir.exists())
            self.assertFalse(
                gate.is_artifact_backed_daily_card(
                    _card(candidate_id="cid-10"),
                    artifact_dir=missing_dir,
                )
            )
            self.assertFalse(missing_dir.exists())


# ---------------------------------------------------------------------------
# Batch filter
# ---------------------------------------------------------------------------


class TestFilterDailySectionCCards(unittest.TestCase):

    def test_returns_admitted_list_and_diagnostics_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_artifact(artifact_dir, candidate_id="a")
            _write_artifact(artifact_dir, candidate_id="b")
            cards = [
                _card(candidate_id="a"),
                _card(candidate_id="b"),
                _card(candidate_id="missing"),
                _card(candidate_id=None),
            ]
            admitted, meta = gate.filter_daily_section_c_cards(
                cards, artifact_dir=artifact_dir,
            )
            self.assertEqual(len(admitted), 2)
            admitted_ids = {c["candidate_id"] for c in admitted}
            self.assertEqual(admitted_ids, {"a", "b"})
            self.assertEqual(
                meta,
                {
                    "gate_id": _GATE_ID,
                    "admitted_count": 2,
                    "held_for_review_count": 2,
                },
            )

    def test_empty_input_returns_empty_admitted_and_zero_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            admitted, meta = gate.filter_daily_section_c_cards(
                [], artifact_dir=Path(tmp),
            )
            self.assertEqual(admitted, [])
            self.assertEqual(meta["admitted_count"], 0)
            self.assertEqual(meta["held_for_review_count"], 0)
            self.assertEqual(meta["gate_id"], _GATE_ID)

    def test_none_input_treated_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            admitted, meta = gate.filter_daily_section_c_cards(
                None, artifact_dir=Path(tmp),
            )
            self.assertEqual(admitted, [])
            self.assertEqual(meta["admitted_count"], 0)
            self.assertEqual(meta["held_for_review_count"], 0)

    def test_filter_does_not_mutate_input_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_artifact(artifact_dir, candidate_id="a")
            cards = [_card(candidate_id="a"), _card(candidate_id="x")]
            original = list(cards)
            gate.filter_daily_section_c_cards(
                cards, artifact_dir=artifact_dir,
            )
            self.assertEqual(cards, original)


# ---------------------------------------------------------------------------
# Planner-spec analyzed_event_artifact fixture
# ---------------------------------------------------------------------------


class TestAnalyzedEventArtifactFixture(unittest.TestCase):
    """Pin admission behaviour against a full planner-spec fixture.

    The planner (``scripts/section_c_daily_artifact_gate_plan.py``)
    enumerates five fields on a reviewed
    ``analyzed_event_artifact_<cid>.json``: ``mechanism_family``,
    ``primary_ticker``, ``benchmark_ticker``, ``market_relevance``
    (operator-supplied, not enforced by v1), and ``candidate_id``.
    The smaller per-field tests above already cover hold-on-missing
    paths; the two regression pins here use a body shaped like the
    real artifact a reviewer would file, and verify (a) admission
    still occurs when extra planner fields are present, and (b) the
    admitted list keeps the original card object — so no future
    refactor of ``filter_daily_section_c_cards`` can silently copy
    or strip the cards as it returns them.

    Read-only contract: tests write the fixture only inside a
    ``TemporaryDirectory`` and never touch the repo's ``artifacts/``.
    """

    def test_full_planner_spec_artifact_admits_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_artifact(
                artifact_dir, candidate_id="cid-planner-1",
                extra={
                    "candidate_id":     "cid-planner-1",
                    "market_relevance": 0.75,
                    "event_id":         "evt-2026-05-15-opec-cuts",
                    "headline":         "OPEC extends voluntary cuts",
                },
            )
            card = _card(candidate_id="cid-planner-1")
            admitted, meta = gate.filter_daily_section_c_cards(
                [card], artifact_dir=artifact_dir,
            )
            self.assertEqual(len(admitted), 1)
            self.assertEqual(meta["admitted_count"],        1)
            self.assertEqual(meta["held_for_review_count"], 0)
            self.assertEqual(meta["gate_id"],               _GATE_ID)

    def test_admitted_card_object_identity_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_artifact(
                artifact_dir, candidate_id="cid-planner-2",
                extra={
                    "candidate_id":     "cid-planner-2",
                    "market_relevance": 0.6,
                },
            )
            card = _card(candidate_id="cid-planner-2")
            admitted, _ = gate.filter_daily_section_c_cards(
                [card], artifact_dir=artifact_dir,
            )
            self.assertEqual(len(admitted), 1)
            # Object identity is the strongest preservation pin: the
            # gate must surface the same dict the caller passed in,
            # so the caller's headline / candidate_id / mechanism on
            # the card remain available downstream to explain why
            # the card was admitted.
            self.assertIs(admitted[0], card)


# ---------------------------------------------------------------------------
# Source-level read-only assertions
# ---------------------------------------------------------------------------


class TestGateModuleSurface(unittest.TestCase):

    def _read(self, rel: str) -> str:
        path = Path(__file__).resolve().parents[1] / rel
        return path.read_text(encoding="utf-8")

    def test_gate_module_has_no_fastapi_or_provider_imports(self) -> None:
        text = self._read("routes/daily_artifact_gate.py").lower()
        for banned in (
            "from fastapi",
            "import fastapi",
            "import yfinance",
            "from yfinance",
            "import market_data",
            "from market_data",
            "openai",
            "anthropic",
        ):
            self.assertNotIn(
                banned, text,
                f"forbidden import {banned!r} seen in daily_artifact_gate.py",
            )

    def test_gate_module_does_not_write_or_delete(self) -> None:
        text = self._read("routes/daily_artifact_gate.py")
        for banned in (
            ".write_text(",
            ".write_bytes(",
            "os.remove(",
            "os.unlink(",
            "shutil.rmtree(",
            'open(',  # any read of a file is allowed only via Path.read_text
        ):
            self.assertNotIn(
                banned, text,
                f"daily_artifact_gate.py contains forbidden call: {banned!r}",
            )


# ---------------------------------------------------------------------------
# Route wiring — text-level (no FastAPI import)
# ---------------------------------------------------------------------------


class TestRouteWiring(unittest.TestCase):
    """Pin that ``routes/movers.py`` imports the gate, applies it on the
    Daily branch only, and surfaces the diagnostics block.

    Read as text — no FastAPI import — to keep this test fast and
    free of the heavy route-import path.
    """

    def setUp(self) -> None:
        self.text = (
            Path(__file__).resolve().parents[1]
            / "routes" / "movers.py"
        ).read_text(encoding="utf-8")

    def test_imports_the_gate_helper(self) -> None:
        self.assertIn(
            "from routes.daily_artifact_gate import",
            self.text,
        )
        self.assertIn("filter_daily_section_c_cards", self.text)

    def test_mentions_analyzed_event_artifact_string(self) -> None:
        # The Section C demo-readiness checklist greps routes/ for
        # this substring as the signal the gate is wired in.  Pin it.
        self.assertIn("analyzed_event_artifact", self.text)

    def test_gate_diagnostics_surface_under_meta(self) -> None:
        self.assertIn("daily_artifact_gate", self.text)

    def test_weekly_route_does_not_call_the_gate(self) -> None:
        # Slice the weekly route body and ensure no call to the gate
        # appears inside it.  The split markers are pinned by the
        # existing decorator boundaries.
        marker_w = '@router.get("/movers/weekly")'
        marker_after = '@router.get("/movers/yearly")'
        i = self.text.find(marker_w)
        j = self.text.find(marker_after, i + 1)
        self.assertGreater(i, 0)
        self.assertGreater(j, i)
        weekly_body = self.text[i:j]
        self.assertNotIn(
            "filter_daily_section_c_cards", weekly_body,
            "weekly route must not invoke the Daily artifact gate",
        )

    def test_persistent_route_does_not_call_the_gate(self) -> None:
        marker_p = '@router.get("/movers/persistent")'
        i = self.text.find(marker_p)
        self.assertGreater(i, 0)
        # Read everything from /movers/persistent to end-of-file to
        # cover the route body fully.
        persistent_body = self.text[i:]
        self.assertNotIn(
            "filter_daily_section_c_cards", persistent_body,
            "persistent route must not invoke the Daily artifact gate",
        )

    def test_weekly_canonicalization_helper_untouched(self) -> None:
        # The weekly canonicalization import and call site must remain.
        self.assertIn(
            "from routes.weekly_canonicalization import "
            "collapse_weekly_duplicates",
            self.text,
        )
        self.assertIn("collapse_weekly_duplicates(", self.text)

    def test_still_moving_persistent_gate_untouched(self) -> None:
        # The Still Moving high-conviction gate import and call site
        # must remain.
        self.assertIn("is_high_conviction_persistent", self.text)

    def test_daily_route_propagates_candidate_id_before_gate(self) -> None:
        # The propagation helper must be called on the Daily branch
        # before the gate so a source-supplied candidate_id flows through.
        self.assertIn("_propagate_daily_candidate_id", self.text)
        marker = '@router.get("/movers/today")'
        marker_after = '@router.get("/movers/weekly")'
        i = self.text.find(marker)
        j = self.text.find(marker_after, i + 1)
        self.assertGreater(i, 0)
        self.assertGreater(j, i)
        today_body = self.text[i:j]
        propagate_pos = today_body.find("_propagate_daily_candidate_id(")
        gate_pos = today_body.find("filter_daily_section_c_cards(")
        self.assertGreater(propagate_pos, 0)
        self.assertGreater(gate_pos, propagate_pos)

    def test_daily_artifact_gate_is_opt_in_via_query_param(self) -> None:
        # Default /movers/today must preserve legacy behavior; the
        # artifact gate is admitted only when the caller opts in via
        # the ``artifact_gate`` query parameter so existing API
        # consumers keep seeing the unfiltered today list.
        marker = '@router.get("/movers/today")'
        marker_after = '@router.get("/movers/weekly")'
        i = self.text.find(marker)
        j = self.text.find(marker_after, i + 1)
        self.assertGreater(i, 0)
        self.assertGreater(j, i)
        today_body = self.text[i:j]
        self.assertIn(
            "artifact_gate", today_body,
            "today route must accept an opt-in artifact_gate flag",
        )
        # The flag must default to False so the legacy contract is
        # preserved when no query param is supplied.
        self.assertIn("artifact_gate: bool = Query(False", today_body)
        # The gate call must be guarded by an ``if`` that reads the
        # flag — no unconditional invocation in the route body.
        flag_guard_pos = today_body.find("if artifact_gate")
        gate_pos = today_body.find("filter_daily_section_c_cards(")
        self.assertGreater(
            flag_guard_pos, 0,
            "today route must guard the gate call with `if artifact_gate`",
        )
        self.assertGreater(
            gate_pos, flag_guard_pos,
            "filter_daily_section_c_cards must be called inside the "
            "if-artifact_gate branch, not before it",
        )

    def test_propagation_helper_not_called_on_weekly_or_persistent(self) -> None:
        weekly_marker = '@router.get("/movers/weekly")'
        yearly_marker = '@router.get("/movers/yearly")'
        persistent_marker = '@router.get("/movers/persistent")'
        i_w = self.text.find(weekly_marker)
        i_y = self.text.find(yearly_marker, i_w + 1)
        self.assertGreater(i_w, 0)
        self.assertGreater(i_y, i_w)
        weekly_body = self.text[i_w:i_y]
        self.assertNotIn(
            "_propagate_daily_candidate_id(", weekly_body,
            "weekly route must not call the Daily candidate_id propagator",
        )
        i_p = self.text.find(persistent_marker)
        self.assertGreater(i_p, 0)
        persistent_body = self.text[i_p:]
        self.assertNotIn(
            "_propagate_daily_candidate_id(", persistent_body,
            "persistent route must not call the Daily candidate_id propagator",
        )


# ---------------------------------------------------------------------------
# Candidate_id propagation helper — read-only pass-through
# ---------------------------------------------------------------------------


class TestPropagateDailyCandidateId(unittest.TestCase):
    """Pin the read-only propagation seam in ``routes/movers.py``.

    The helper surfaces a normalized ``candidate_id`` on each Daily
    card when one is already available from the source card.  It does
    not invent or derive an id — when the source carries no
    non-empty string the field is left absent and the artifact gate
    would hold the card for review.
    """

    def setUp(self) -> None:
        self.propagate = _load_movers_function("_propagate_daily_candidate_id")

    def test_propagates_string_candidate_id_unchanged(self) -> None:
        cards = [{"event_id": 1, "candidate_id": "cid-abc"}]
        out = self.propagate(cards)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["candidate_id"], "cid-abc")

    def test_strips_surrounding_whitespace_on_candidate_id(self) -> None:
        cards = [{"candidate_id": "  cid-abc  "}]
        out = self.propagate(cards)
        self.assertEqual(out[0]["candidate_id"], "cid-abc")

    def test_does_not_invent_candidate_id_when_source_has_none(self) -> None:
        cards = [{"event_id": 7, "headline": "h"}]
        out = self.propagate(cards)
        self.assertEqual(len(out), 1)
        self.assertNotIn("candidate_id", out[0])

    def test_does_not_invent_candidate_id_when_source_value_blank(self) -> None:
        cards = [{"candidate_id": "   "}]
        out = self.propagate(cards)
        # Blank source value left as-is; gate will hold the card.
        self.assertEqual(out[0].get("candidate_id"), "   ")

    def test_does_not_invent_candidate_id_when_source_value_not_string(self) -> None:
        cards = [{"candidate_id": 12345}]
        out = self.propagate(cards)
        self.assertEqual(out[0].get("candidate_id"), 12345)

    def test_does_not_mutate_input_dicts_or_list(self) -> None:
        original = {"event_id": 1, "candidate_id": "  cid-xyz  "}
        snapshot = dict(original)
        cards = [original]
        cards_snapshot = list(cards)
        self.propagate(cards)
        self.assertEqual(original, snapshot)
        self.assertEqual(cards, cards_snapshot)

    def test_passes_through_non_dict_entries(self) -> None:
        cards = [None, "not a card", {"candidate_id": "cid-1"}]
        out = self.propagate(cards)
        self.assertEqual(len(out), 3)
        self.assertIsNone(out[0])
        self.assertEqual(out[1], "not a card")
        self.assertEqual(out[2]["candidate_id"], "cid-1")

    def test_handles_empty_and_none_input(self) -> None:
        self.assertEqual(self.propagate([]), [])
        self.assertEqual(self.propagate(None), [])

    def test_propagation_then_gate_admits_when_artifact_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            _write_artifact(artifact_dir, candidate_id="cid-prop")
            cards = [{"event_id": 1, "candidate_id": "cid-prop"}]
            with_cid = self.propagate(cards)
            admitted, meta = gate.filter_daily_section_c_cards(
                with_cid, artifact_dir=artifact_dir,
            )
            self.assertEqual(len(admitted), 1)
            self.assertEqual(meta["admitted_count"], 1)
            self.assertEqual(meta["held_for_review_count"], 0)

    def test_propagation_then_gate_holds_when_candidate_id_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cards = [{"event_id": 1, "headline": "h"}]
            with_cid = self.propagate(cards)
            admitted, meta = gate.filter_daily_section_c_cards(
                with_cid, artifact_dir=Path(tmp),
            )
            self.assertEqual(admitted, [])
            self.assertEqual(meta["held_for_review_count"], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
