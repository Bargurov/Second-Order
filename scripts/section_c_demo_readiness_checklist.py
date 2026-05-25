#!/usr/bin/env python3
"""Section C — demo-readiness checklist.

Read-only checklist that asks, for the six narrow checks the spec
pins, whether Section C looks ready for the 2-month demo target.
The checklist describes the state of the repo today; it never
mutates a file, never connects to a DB, and never claims demo
readiness on its own — the operator owns the final approval.

Read-only by construction
-------------------------

* Single source of truth: files already on disk.  The checklist
  reads ``routes/movers.py``, ``routes/weekly_canonicalization.py``,
  ``mover_card_normalizer.py``, ``scripts/no_paid_smoke.py``, and
  ``artifacts/freeze_candidate_evidence.json`` in read-mode only.
* No DB connection.  No ``yfinance`` / ``market_data`` / paid
  provider / LLM call.  No FastAPI surface (never imports ``api``
  or ``routes.*`` at module load — even the ``routes.*`` paths the
  checklist inspects are read as text files, not imported as
  Python modules).
* The freeze-candidate artifact validator is reached through a
  thin lazy seam so tests can patch the call directly and the
  checklist's top-level import surface stays narrow.
* ``--output`` is the only filesystem side effect, and only when
  explicitly passed.  The checklist itself produces no other file.

Required checks (spec order)
----------------------------

1. ``weekly_duplicate_canonicalization_landed`` — the production
   weekly route imports and invokes
   ``routes.weekly_canonicalization.collapse_weekly_duplicates``,
   and the helper module exists on disk.
2. ``still_moving_sector_etf_primary_gate_landed`` — the persistent
   high-conviction Still Moving gate refuses cards whose top mover
   is a sector ETF; the test for ``primary_is_sector_etf`` is wired
   into ``mover_card_normalizer.is_high_conviction_persistent``.
3. ``daily_mechanism_family_enrichment_resolved`` — the Daily
   inbox-to-Section-C path either carries a ``mechanism_family``
   value at promotion time OR a Section C boundary gate refuses
   to promote candidates whose analyzed-event artifact is missing.
   Until the artifact gate is wired in or at least one
   ``analyzed_event_artifact_<cid>.json`` under ``artifacts/``
   carries the three required fields the gate enforces, this
   check is a blocker — per the recommendation in
   :mod:`scripts.section_c_daily_mechanism_enrichment_plan`.
   Each candidate artifact is inspected once for the three
   required fields (``mechanism_family`` not the ``"none"``
   sentinel, ``primary_ticker``, ``benchmark_ticker``); evidence
   carries ``artifact_count``, ``valid_artifact_count``,
   ``invalid_artifact_count``, and up to five missing-field
   examples so the operator can repair invalid artifacts before
   the demo.  The check also surfaces — but does not promote
   on — the presence of a dedicated fixture-backed gate smoke
   (``scripts/daily_artifact_gate_fixture_smoke.py``) so the
   operator can distinguish "gate wired but no real candidates
   yet," "gate mechanics exercisable by fixture smoke but no
   real candidates yet," and "gate wired with at least one
   valid real artifact-backed candidate."  Only the third state
   lifts the check to passed; the others remain partial so the
   readiness status stays ``required_checks_pending`` until real
   Daily candidates exist.  Like ``no_paid_smoke.py``, the
   fixture smoke is not executed by the checklist — running it
   stays the operator's responsibility, and the smoke's
   tempdir-scoped artifacts are never read here.
4. ``freeze_candidate_evidence_artifact_validates`` — the existing
   ``artifacts/freeze_candidate_evidence.json`` file passes
   :mod:`scripts.validate_freeze_candidate_artifact`.
5. ``benchmark_sensitivity_event_60_honest_representation`` — the
   freeze-candidate artifact lists event 60 in
   ``benchmark_sensitivity_status.changed_event_ids``, reports a
   non-zero ``changed_interpretation_count``, every event-60 record
   carries ``fdr_significant == False`` under the chosen benchmark,
   and the ``limitations`` list carries the "no FDR-significant"
   caveat.
6. ``no_paid_smoke_available`` — ``scripts/no_paid_smoke.py``
   exists on disk.  The checklist does not run the smoke
   itself — running it is the operator's responsibility before
   the demo because it exercises the in-process FastAPI surface
   and that is outside this checklist's read-only contract.

Each check's verdict lands in exactly one of ``passed_checks``,
``partial_checks``, or ``blockers``.  ``required_before_demo``
collects the next-action prose for every partial or blocked check;
``optional_before_demo`` carries any nice-to-have action the
checklist surfaces.

Conservative wording
--------------------

Banned tokens in any emitted prose: ``proof``, ``proven``,
``guaranteed``, ``automatically``, ``validated``,
``alpha generated``, ``correct ticker``, ``definitely``,
``approved``, ``production ready``, ``production-ready``.  The
checklist also refuses to surface a flat ``"demo_ready"`` token
as a readiness status — the strongest claim it makes is
``"required_checks_passed"``, leaving the demo decision with the
operator.

Output contract (JSON)::

    {
      "ok":                  bool,
      "readiness_status":    "blocked"
                             | "required_checks_pending"
                             | "required_checks_passed",
      "blockers":            [ {check_dict}, ... ],
      "passed_checks":       [ {check_dict}, ... ],
      "partial_checks":      [ {check_dict}, ... ],
      "required_before_demo":[str, ...],
      "optional_before_demo":[str, ...],
      "warnings":            [str, ...],
      "errors":              [str, ...],
    }

Each ``check_dict`` carries::

    {
      "check_id":    str,
      "description": str,
      "required":    bool,
      "status":      "passed" | "partial" | "blocked",
      "evidence":    [str, ...],
      "next_action": str,
    }

Usage::

    python scripts/section_c_demo_readiness_checklist.py --json
    python scripts/section_c_demo_readiness_checklist.py --json \\
        --repo-root . \\
        --freeze-artifact artifacts/freeze_candidate_evidence.json \\
        --output artifacts/section_c_demo_readiness_checklist.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Check identifiers — named once, referenced by every code path that
# emits or classifies a check.  Tests pin the catalogue so a future
# drift gets caught.
# ---------------------------------------------------------------------------


_CHECK_WEEKLY:       str = "weekly_duplicate_canonicalization_landed"
_CHECK_SECTOR_ETF:   str = "still_moving_sector_etf_primary_gate_landed"
_CHECK_DAILY_ENRICH: str = "daily_mechanism_family_enrichment_resolved"
_CHECK_FREEZE_OK:    str = "freeze_candidate_evidence_artifact_validates"
_CHECK_EVENT_60:     str = "benchmark_sensitivity_event_60_honest_representation"
_CHECK_NO_PAID:      str = "no_paid_smoke_available"


_REQUIRED_CHECK_IDS: tuple[str, ...] = (
    _CHECK_WEEKLY,
    _CHECK_SECTOR_ETF,
    _CHECK_DAILY_ENRICH,
    _CHECK_FREEZE_OK,
    _CHECK_EVENT_60,
    _CHECK_NO_PAID,
)


_STATUS_PASSED:  str = "passed"
_STATUS_PARTIAL: str = "partial"
_STATUS_BLOCKED: str = "blocked"


_READINESS_BLOCKED: str = "blocked"
_READINESS_PENDING: str = "required_checks_pending"
_READINESS_PASSED:  str = "required_checks_passed"


_DEFAULT_FREEZE_ARTIFACT: str = "artifacts/freeze_candidate_evidence.json"


# ---------------------------------------------------------------------------
# Patchable seam — lazy import of the freeze-candidate validator.
# ---------------------------------------------------------------------------


def _run_freeze_validator(*, artifact_path: str) -> dict[str, Any]:
    """Validate the freeze-candidate evidence artifact.

    Lazy-imports the validator so the checklist's top-level import
    surface stays narrow.  Tests patch this seam directly so they
    never depend on the on-disk artifact.
    """
    from scripts.validate_freeze_candidate_artifact import (
        run_validate_freeze_candidate_artifact,
    )
    return run_validate_freeze_candidate_artifact(
        artifact_path=artifact_path,
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_section_c_demo_readiness_checklist(
    *,
    repo_root:        str | None = None,
    freeze_artifact:  str | None = None,
    output_path:      str | None = None,
) -> dict[str, Any]:
    """Build the demo-readiness checklist.

    See module docstring for the full output contract.
    """
    warnings: list[str] = []
    errors:   list[str] = []

    root = Path(repo_root) if repo_root else ROOT
    freeze_path = freeze_artifact or str(root / _DEFAULT_FREEZE_ARTIFACT)

    checks: list[dict[str, Any]] = []
    checks.append(_check_weekly_canonicalization_landed(repo_root=root))
    checks.append(_check_sector_etf_gate_landed(repo_root=root))
    checks.append(_check_daily_mechanism_enrichment_resolved(repo_root=root))
    checks.append(_check_freeze_artifact_validates(
        freeze_artifact_path=freeze_path, errors=errors,
    ))
    checks.append(_check_event_60_honestly_represented(
        freeze_artifact_path=freeze_path, warnings=warnings,
    ))
    checks.append(_check_no_paid_smoke_available(repo_root=root))

    passed:   list[dict[str, Any]] = []
    partial:  list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for c in checks:
        status = c.get("status")
        if status == _STATUS_PASSED:
            passed.append(c)
        elif status == _STATUS_PARTIAL:
            partial.append(c)
        else:
            # Any non-passed, non-partial status (including unknown)
            # lands in blockers so the operator sees it.
            blockers.append(c)

    # Required-vs-optional split for the operator action lists.  A
    # required check that lands in partial or blocked produces a
    # required_before_demo action.  An optional check (we have none
    # in the v1 spec, but the field is reserved) lands in
    # optional_before_demo.
    required_before_demo: list[str] = []
    optional_before_demo: list[str] = []
    for c in checks:
        if c.get("status") == _STATUS_PASSED:
            continue
        action = c.get("next_action") or ""
        if not isinstance(action, str) or not action:
            continue
        if c.get("required") is True:
            required_before_demo.append(action)
        else:
            optional_before_demo.append(action)

    readiness = _classify_readiness(
        blockers=blockers, partial=partial,
        required_check_ids=set(_REQUIRED_CHECK_IDS),
    )

    envelope: dict[str, Any] = {
        "ok":                   not errors and readiness != _READINESS_BLOCKED,
        "readiness_status":     readiness,
        "blockers":             blockers,
        "passed_checks":        passed,
        "partial_checks":       partial,
        "required_before_demo": required_before_demo,
        "optional_before_demo": optional_before_demo,
        "warnings":             warnings,
        "errors":               errors,
    }

    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, indent=2, sort_keys=True, default=str)
        except OSError as exc:
            envelope["errors"].append(
                f"failed to write --output {output_path}: {exc}"
            )
            envelope["ok"] = False

    return envelope


# ---------------------------------------------------------------------------
# Per-check builders
# ---------------------------------------------------------------------------


def _check_weekly_canonicalization_landed(
    *, repo_root: Path,
) -> dict[str, Any]:
    description = (
        "Weekly Market route imports and invokes the production "
        "collapse_weekly_duplicates helper so a duplicate cluster "
        "lands as one canonical card carrying duplicate_count and "
        "grouped_event_ids."
    )
    helper_path = repo_root / "routes" / "weekly_canonicalization.py"
    movers_path = repo_root / "routes" / "movers.py"

    evidence: list[str] = []
    helper_present = helper_path.is_file()
    if helper_present:
        evidence.append(
            f"helper file present: {helper_path.as_posix()}"
        )
    else:
        evidence.append(
            f"helper file missing: {helper_path.as_posix()}"
        )

    movers_present = movers_path.is_file()
    wired_in = False
    if movers_present:
        try:
            movers_text = movers_path.read_text(encoding="utf-8")
        except OSError as exc:
            evidence.append(
                f"routes/movers.py could not be read: "
                f"{type(exc).__name__}"
            )
            movers_text = ""
        if (
            "from routes.weekly_canonicalization import "
            "collapse_weekly_duplicates" in movers_text
            and "collapse_weekly_duplicates(" in movers_text
        ):
            wired_in = True
            evidence.append(
                "routes/movers.py imports and calls "
                "collapse_weekly_duplicates"
            )
        else:
            evidence.append(
                "routes/movers.py does not appear to import and "
                "call collapse_weekly_duplicates"
            )
    else:
        evidence.append(
            f"routes/movers.py is missing at {movers_path.as_posix()}"
        )

    if helper_present and wired_in:
        return _check_record(
            check_id=_CHECK_WEEKLY,
            description=description,
            required=True,
            status=_STATUS_PASSED,
            evidence=evidence,
            next_action="",
        )
    return _check_record(
        check_id=_CHECK_WEEKLY,
        description=description,
        required=True,
        status=_STATUS_BLOCKED,
        evidence=evidence,
        next_action=(
            "wire routes.weekly_canonicalization.collapse_weekly_duplicates "
            "into the weekly Market route in routes/movers.py before the "
            "demo; the helper exists but the import or call site is "
            "missing on this run"
        ),
    )


def _check_sector_etf_gate_landed(
    *, repo_root: Path,
) -> dict[str, Any]:
    description = (
        "Still Moving Markets persistent gate refuses a card whose "
        "top mover is a sector ETF (primary_is_sector_etf returns "
        "True); the helper is wired into "
        "is_high_conviction_persistent."
    )
    norm_path = repo_root / "mover_card_normalizer.py"
    evidence: list[str] = []

    if not norm_path.is_file():
        evidence.append(
            f"mover_card_normalizer.py is missing at "
            f"{norm_path.as_posix()}"
        )
        return _check_record(
            check_id=_CHECK_SECTOR_ETF,
            description=description,
            required=True,
            status=_STATUS_BLOCKED,
            evidence=evidence,
            next_action=(
                "restore mover_card_normalizer.py — the sector-ETF "
                "primary gate lives in this module"
            ),
        )

    try:
        text = norm_path.read_text(encoding="utf-8")
    except OSError as exc:
        evidence.append(
            f"mover_card_normalizer.py could not be read: "
            f"{type(exc).__name__}"
        )
        return _check_record(
            check_id=_CHECK_SECTOR_ETF,
            description=description,
            required=True,
            status=_STATUS_BLOCKED,
            evidence=evidence,
            next_action=(
                "inspect filesystem permissions on "
                "mover_card_normalizer.py — the checklist could not "
                "read it"
            ),
        )

    helper_defined = "def primary_is_sector_etf(" in text
    # Count every occurrence of the bare call form `primary_is_sector_etf(`
    # and subtract the one from the `def` line.  When the helper is
    # both defined and referenced, the count is >= 2 (definition +
    # at least one call site).  Counting beats substring matching
    # because the definition itself contains `primary_is_sector_etf(`.
    total_refs   = text.count("primary_is_sector_etf(")
    def_refs     = text.count("def primary_is_sector_etf(")
    call_refs    = total_refs - def_refs
    helper_called = call_refs > 0

    if helper_defined:
        evidence.append(
            "mover_card_normalizer.primary_is_sector_etf is defined"
        )
    else:
        evidence.append(
            "mover_card_normalizer.primary_is_sector_etf is not "
            "defined"
        )
    if helper_called:
        evidence.append(
            "primary_is_sector_etf is referenced inside "
            "mover_card_normalizer.py (gate is wired)"
        )
    else:
        evidence.append(
            "primary_is_sector_etf is not referenced inside the "
            "persistent gate"
        )

    if helper_defined and helper_called:
        return _check_record(
            check_id=_CHECK_SECTOR_ETF,
            description=description,
            required=True,
            status=_STATUS_PASSED,
            evidence=evidence,
            next_action="",
        )
    return _check_record(
        check_id=_CHECK_SECTOR_ETF,
        description=description,
        required=True,
        status=_STATUS_BLOCKED,
        evidence=evidence,
        next_action=(
            "wire primary_is_sector_etf into "
            "is_high_conviction_persistent in "
            "mover_card_normalizer.py so the sector-ETF primary "
            "gate refuses sector-ETF top movers before promotion"
        ),
    )


def _check_daily_mechanism_enrichment_resolved(
    *, repo_root: Path,
) -> dict[str, Any]:
    description = (
        "Daily inbox candidates either carry a mechanism_family "
        "value at Section C promotion time, or the Section C "
        "boundary refuses to promote candidates whose analyzed-"
        "event artifact is missing.  Until the artifact gate is "
        "wired in (or at least one analyzed_event_artifact_<cid>.json "
        "carries the three required fields the gate enforces), this "
        "check is a blocker per the planner's recommendation.  A "
        "fixture-backed smoke covering the gate mechanics raises "
        "confidence in the wiring but is not a substitute for real "
        "artifact-backed Daily candidates.  Artifact files that "
        "exist on disk but are missing required fields are surfaced "
        "as invalid in evidence so the operator can repair them."
    )
    artifacts_dir = repo_root / "artifacts"
    routes_dir = repo_root / "routes"
    tests_dir = repo_root / "tests"
    evidence: list[str] = []

    # --- Signal 1: real analyzed_event_artifact files + validity ------
    # ``analyzed_event_artifact_*.json`` mirrors the gate's exact
    # convention (candidate_id suffixed after the prefix).  Each
    # file is read once and inspected for the three required
    # fields the gate enforces.  Files that exist on disk but fail
    # validation count toward ``invalid_artifact_count`` only —
    # they never raise ``valid_artifact_count`` and never lift the
    # check to passed.  The fixture smoke writes its artifacts to
    # a ``tempfile.TemporaryDirectory`` under Python's tempdir, so
    # the smoke's synthetic candidates never appear under
    # ``artifacts/`` and are not mistaken for real production
    # candidates here.
    analyzed_files: list[Path] = []
    artifact_count: int = 0
    valid_artifact_count: int = 0
    invalid_artifact_count: int = 0
    invalid_artifact_examples: list[str] = []
    if artifacts_dir.is_dir():
        analyzed_files = sorted(
            artifacts_dir.glob("analyzed_event_artifact_*.json")
        )
        artifact_count = len(analyzed_files)
        for p in analyzed_files:
            verdict = _artifact_validity_check(p)
            if verdict.get("ok") is True:
                valid_artifact_count += 1
            else:
                invalid_artifact_count += 1
                if len(invalid_artifact_examples) < 5:
                    reason = verdict.get("reason") or "invalid"
                    invalid_artifact_examples.append(
                        f"{p.name} - {reason}"
                    )
    else:
        evidence.append(
            f"artifacts/ directory is missing at "
            f"{artifacts_dir.as_posix()}"
        )
    evidence.append(f"artifact_count: {artifact_count}")
    evidence.append(f"valid_artifact_count: {valid_artifact_count}")
    evidence.append(f"invalid_artifact_count: {invalid_artifact_count}")
    for ex in invalid_artifact_examples:
        evidence.append(f"invalid artifact: {ex}")
    real_artifacts_present = valid_artifact_count > 0

    # --- Signal 2: gate wired into routes/ ----------------------------
    # Look for any source-level evidence that an artifact gate has
    # been wired in.  We grep for the artifact name in routes/ as a
    # cheap proxy.  Absence is not conclusive — the operator may have
    # used a different convention — but its absence with zero
    # analyzed artifacts is the conservative blocker the spec asks
    # for.
    gate_wired_in_routes = False
    if routes_dir.is_dir():
        for py in routes_dir.glob("*.py"):
            try:
                if "analyzed_event_artifact" in py.read_text(
                    encoding="utf-8",
                ):
                    gate_wired_in_routes = True
                    evidence.append(
                        f"analyzed_event_artifact reference found "
                        f"in {py.as_posix()}"
                    )
                    break
            except OSError:
                continue
    if not gate_wired_in_routes:
        evidence.append(
            "no analyzed_event_artifact reference found under "
            "routes/; the Section C boundary gate does not appear "
            "to be wired in"
        )

    # --- Signal 3: fixture-backed gate smoke present on disk ----------
    # The dedicated read-only fixture smoke lives at
    # ``scripts/daily_artifact_gate_fixture_smoke.py``.  Its
    # presence raises confidence that the gate's mechanics can be
    # exercised under a deterministic fixture (the smoke owns its
    # own tempdir and never touches the real ``artifacts/``).  The
    # checklist does not run the smoke itself — that is the
    # operator's responsibility, just like ``no_paid_smoke.py`` — it
    # only checks that the script is on disk.
    #
    # This signal is informational: it never lifts the check to
    # passed on its own, because demo readiness still requires real
    # artifact-backed Daily candidates.
    fixture_smoke_path = (
        repo_root / "scripts" / "daily_artifact_gate_fixture_smoke.py"
    )
    fixture_smoke_test_path = (
        tests_dir / "test_daily_artifact_gate_fixture_smoke.py"
    )
    fixture_smoke_present = fixture_smoke_path.is_file()
    fixture_smoke_test_present = fixture_smoke_test_path.is_file()
    if fixture_smoke_present:
        evidence.append(
            f"fixture-backed gate smoke present at "
            f"{fixture_smoke_path.as_posix()} — gate mechanics can "
            f"be exercised by this fixture smoke; real artifact-"
            f"backed Daily candidates are still required before "
            f"the demo"
        )
    else:
        evidence.append(
            f"fixture-backed gate smoke missing at "
            f"{fixture_smoke_path.as_posix()}"
        )
    if fixture_smoke_test_present:
        evidence.append(
            f"fixture-smoke unit-test present at "
            f"{fixture_smoke_test_path.as_posix()}"
        )
    else:
        evidence.append(
            f"fixture-smoke unit-test missing at "
            f"{fixture_smoke_test_path.as_posix()}"
        )

    # --- Verdict ------------------------------------------------------
    if gate_wired_in_routes and real_artifacts_present:
        return _check_record(
            check_id=_CHECK_DAILY_ENRICH,
            description=description,
            required=True,
            status=_STATUS_PASSED,
            evidence=evidence,
            next_action="",
        )
    if gate_wired_in_routes or real_artifacts_present:
        # At least one half is in place — surface as partial so the
        # operator sees the progress.  When the fixture smoke
        # exercises the gate mechanics but no real artifacts are on
        # disk yet, tailor the next-action to call out that fixture
        # coverage alone does not establish readiness for the demo.
        if (
            gate_wired_in_routes
            and not real_artifacts_present
            and invalid_artifact_count > 0
        ):
            # Files are on disk but none carry the three required
            # fields the gate enforces.  Tell the operator
            # explicitly to repair the invalid artifacts rather
            # than to populate more.
            next_action = (
                "the gate is wired into routes/ and "
                f"{artifact_count} analyzed_event_artifact_<cid>"
                f".json file(s) are present under artifacts/, but "
                f"{invalid_artifact_count} of them is/are missing "
                "one or more of the three required fields "
                "(mechanism_family != 'none' sentinel, "
                "primary_ticker, benchmark_ticker) — repair the "
                "invalid artifact(s) before the demo, OR replace "
                "them with reviewed analyzed_event_artifact_<cid>"
                ".json files carrying the three required fields. "
                "Fixture coverage alone does not establish "
                "readiness of the Daily path for the demo."
            )
        elif (
            fixture_smoke_present
            and gate_wired_in_routes
            and not real_artifacts_present
        ):
            next_action = (
                "the gate is wired into routes/ and the fixture-"
                "backed gate smoke "
                "(scripts/daily_artifact_gate_fixture_smoke.py) is "
                "on disk so the gate's admit/hold mechanics can be "
                "exercised separately by the operator, but no real "
                "analyzed_event_artifact_<cid>.json files are "
                "present under artifacts/ yet — produce a reviewed "
                "analyzed_event_artifact_<cid>.json for every Daily "
                "candidate before the demo, and run "
                "`python scripts/daily_artifact_gate_fixture_smoke.py"
                " --json` separately to confirm summary.ok == True. "
                "Fixture coverage alone does not establish readiness "
                "of the Daily path for the demo."
            )
        else:
            next_action = (
                "complete the Daily mechanism-family enrichment "
                "path: either populate analyzed_event_artifact "
                "files under artifacts/ for every Daily candidate "
                "OR wire the Section C boundary gate into routes/ "
                "so candidates without an artifact are refused"
            )
        return _check_record(
            check_id=_CHECK_DAILY_ENRICH,
            description=description,
            required=True,
            status=_STATUS_PARTIAL,
            evidence=evidence,
            next_action=next_action,
        )
    return _check_record(
        check_id=_CHECK_DAILY_ENRICH,
        description=description,
        required=True,
        status=_STATUS_BLOCKED,
        evidence=evidence,
        next_action=(
            "adopt the planner's recommendation "
            "(require_analyzed_event_artifact_before_section_c_inclusion) "
            "before the demo: produce one analyzed-event artifact per "
            "Daily candidate AND wire the Section C boundary gate so "
            "promotion is refused when the artifact is missing"
        ),
    )


def _check_freeze_artifact_validates(
    *,
    freeze_artifact_path: str,
    errors:               list[str],
) -> dict[str, Any]:
    description = (
        "The freeze-candidate evidence artifact "
        "(artifacts/freeze_candidate_evidence.json) passes its "
        "schema validator on this run."
    )
    evidence: list[str] = [
        f"artifact path: {freeze_artifact_path}",
    ]

    try:
        report = _run_freeze_validator(
            artifact_path=freeze_artifact_path,
        )
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"freeze-candidate validator raised: "
            f"{type(exc).__name__}: {exc}"
        )
        evidence.append(
            f"validator raised {type(exc).__name__}; the check "
            f"surfaces this as a blocker"
        )
        return _check_record(
            check_id=_CHECK_FREEZE_OK,
            description=description,
            required=True,
            status=_STATUS_BLOCKED,
            evidence=evidence,
            next_action=(
                "inspect artifacts/freeze_candidate_evidence.json — "
                "the validator raised an exception before it could "
                "settle a verdict"
            ),
        )

    ok = bool(report.get("ok"))
    records_count = report.get("records_count")
    if isinstance(records_count, int):
        evidence.append(f"records_count = {records_count}")
    val_errors = report.get("errors") or []
    val_warnings = report.get("warnings") or []
    if val_errors:
        evidence.append(
            f"validator surfaced {len(val_errors)} error(s)"
        )
    if val_warnings:
        evidence.append(
            f"validator surfaced {len(val_warnings)} warning(s)"
        )

    if ok and not val_errors:
        return _check_record(
            check_id=_CHECK_FREEZE_OK,
            description=description,
            required=True,
            status=_STATUS_PASSED,
            evidence=evidence,
            next_action="",
        )
    return _check_record(
        check_id=_CHECK_FREEZE_OK,
        description=description,
        required=True,
        status=_STATUS_BLOCKED,
        evidence=evidence,
        next_action=(
            "address the freeze-candidate validator errors before "
            "the demo backend is allowed to consume this artifact"
        ),
    )


def _check_event_60_honestly_represented(
    *,
    freeze_artifact_path: str,
    warnings:             list[str],
) -> dict[str, Any]:
    description = (
        "The freeze-candidate evidence artifact represents event "
        "60 honestly: event 60 appears in "
        "benchmark_sensitivity_status.changed_event_ids, the "
        "changed_interpretation_count is non-zero, every event-60 "
        "record carries fdr_significant == False under the "
        "selected benchmark, and the limitations list carries the "
        "no-FDR-significant caveat."
    )
    evidence: list[str] = []

    path = Path(freeze_artifact_path)
    if not path.is_file():
        evidence.append(
            f"artifact missing on disk: {freeze_artifact_path}"
        )
        return _check_record(
            check_id=_CHECK_EVENT_60,
            description=description,
            required=True,
            status=_STATUS_BLOCKED,
            evidence=evidence,
            next_action=(
                "produce artifacts/freeze_candidate_evidence.json "
                "before the demo — the event-60 honesty check "
                "cannot run without it"
            ),
        )

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(
            f"event-60 honesty check could not parse "
            f"{freeze_artifact_path!r}: "
            f"{type(exc).__name__}: {exc}"
        )
        evidence.append(
            f"artifact could not be parsed: {type(exc).__name__}"
        )
        return _check_record(
            check_id=_CHECK_EVENT_60,
            description=description,
            required=True,
            status=_STATUS_BLOCKED,
            evidence=evidence,
            next_action=(
                "fix the JSON parse error in "
                "artifacts/freeze_candidate_evidence.json before "
                "the demo"
            ),
        )

    if not isinstance(data, dict):
        evidence.append("artifact did not parse as a JSON object")
        return _check_record(
            check_id=_CHECK_EVENT_60,
            description=description,
            required=True,
            status=_STATUS_BLOCKED,
            evidence=evidence,
            next_action=(
                "regenerate artifacts/freeze_candidate_evidence.json "
                "— the artifact root is not a JSON object"
            ),
        )

    bench = data.get("benchmark_sensitivity_status")
    if not isinstance(bench, dict):
        bench = {}
    changed_ids_raw = bench.get("changed_event_ids") or []
    changed_ids = [
        e for e in changed_ids_raw
        if isinstance(e, int) and not isinstance(e, bool)
    ]
    event_60_in_changed = 60 in changed_ids
    evidence.append(
        f"60 in benchmark_sensitivity_status.changed_event_ids: "
        f"{event_60_in_changed}"
    )

    changed_count_raw = bench.get("changed_interpretation_count")
    changed_count = (
        changed_count_raw
        if isinstance(changed_count_raw, int)
        and not isinstance(changed_count_raw, bool)
        else 0
    )
    evidence.append(
        f"benchmark_sensitivity_status.changed_interpretation_count "
        f"= {changed_count}"
    )

    records = data.get("records") or []
    event_60_records: list[dict[str, Any]] = []
    for r in records:
        if isinstance(r, dict) and r.get("event_id") == 60:
            event_60_records.append(r)
    evidence.append(
        f"event-60 record count in records[]: "
        f"{len(event_60_records)}"
    )

    every_record_not_fdr_significant = (
        len(event_60_records) > 0
        and all(
            r.get("fdr_significant") is False
            for r in event_60_records
        )
    )
    evidence.append(
        f"every event-60 record has fdr_significant == False: "
        f"{every_record_not_fdr_significant}"
    )

    limitations = data.get("limitations") or []
    limitations_text = " | ".join(
        s for s in limitations if isinstance(s, str)
    ).lower()
    no_fdr_caveat_present = "no fdr-significant" in limitations_text
    evidence.append(
        f"limitations carry the 'no FDR-significant' caveat: "
        f"{no_fdr_caveat_present}"
    )

    all_signals = (
        event_60_in_changed
        and changed_count > 0
        and every_record_not_fdr_significant
        and no_fdr_caveat_present
    )
    if all_signals:
        return _check_record(
            check_id=_CHECK_EVENT_60,
            description=description,
            required=True,
            status=_STATUS_PASSED,
            evidence=evidence,
            next_action="",
        )

    # When at least one signal is present but not all, mark
    # partial; when nothing lines up, mark blocked.
    any_signal = (
        event_60_in_changed
        or changed_count > 0
        or every_record_not_fdr_significant
        or no_fdr_caveat_present
    )
    if any_signal:
        return _check_record(
            check_id=_CHECK_EVENT_60,
            description=description,
            required=True,
            status=_STATUS_PARTIAL,
            evidence=evidence,
            next_action=(
                "regenerate artifacts/freeze_candidate_evidence.json "
                "so event 60 surfaces in changed_event_ids with a "
                "non-zero changed_interpretation_count, every "
                "event-60 record carries fdr_significant == False, "
                "and the no-FDR caveat is present in limitations"
            ),
        )
    return _check_record(
        check_id=_CHECK_EVENT_60,
        description=description,
        required=True,
        status=_STATUS_BLOCKED,
        evidence=evidence,
        next_action=(
            "regenerate artifacts/freeze_candidate_evidence.json "
            "and confirm event 60's representation lines up with "
            "the four honesty signals before the demo"
        ),
    )


def _check_no_paid_smoke_available(
    *, repo_root: Path,
) -> dict[str, Any]:
    description = (
        "scripts/no_paid_smoke.py exists on disk so the operator "
        "can run the no-paid in-process smoke separately before "
        "the demo.  The checklist does not run the smoke itself — "
        "that exercises a FastAPI surface and is outside this "
        "checklist's read-only contract."
    )
    smoke_path = repo_root / "scripts" / "no_paid_smoke.py"
    evidence: list[str] = [
        f"smoke path: {smoke_path.as_posix()}",
    ]

    if not smoke_path.is_file():
        evidence.append("smoke script is missing on disk")
        return _check_record(
            check_id=_CHECK_NO_PAID,
            description=description,
            required=True,
            status=_STATUS_BLOCKED,
            evidence=evidence,
            next_action=(
                "restore scripts/no_paid_smoke.py before the demo — "
                "the no-paid in-process smoke is the operator's gate "
                "on demo-time paid-surface regressions"
            ),
        )

    evidence.append("smoke script present on disk")
    # The smoke is available but unrun — partial, not passed, so
    # the operator action shows up in required_before_demo.
    return _check_record(
        check_id=_CHECK_NO_PAID,
        description=description,
        required=True,
        status=_STATUS_PARTIAL,
        evidence=evidence,
        next_action=(
            "run `python scripts/no_paid_smoke.py --json` "
            "separately before the demo and confirm summary.failed "
            "== 0; the checklist does not run the smoke in-process"
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Required artifact fields the Daily Section C gate enforces.  This
# checklist mirrors the gate's validation contract from
# ``routes/daily_artifact_gate.py`` (mechanism_family !=
# ``"none"`` sentinel; primary_ticker and benchmark_ticker
# non-empty).  The fourth planner field, ``market_relevance``, is
# operator-supplied at review time and is not enforced here.
#
# The name is intentionally prefixed with ``_CHECKLIST_`` so it
# does not collide with the gate module's own private
# ``_REQUIRED_ARTIFACT_FIELDS``.  The two are kept aligned by
# convention — when the gate's contract changes, this constant
# must be updated in lockstep; tests pin the behavioural overlap.
_CHECKLIST_REQUIRED_ARTIFACT_FIELDS: tuple[str, ...] = (
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
)
_CHECKLIST_MECHANISM_FAMILY_NONE_SENTINEL: str = "none"


def _artifact_validity_check(path: Path) -> dict[str, Any]:
    """Inspect an ``analyzed_event_artifact_<cid>.json`` file for the
    three required fields the Daily Section C gate enforces.

    Returns a small dict::

        {"ok": bool, "reason": str}

    Read-only by construction — the file is opened with
    :meth:`Path.read_text` and is never written or removed.  The
    rule mirrors :func:`routes.daily_artifact_gate._artifact_has_required_fields`
    so a file the gate would admit is the same file this checklist
    flags as valid.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "ok":     False,
            "reason": f"unreadable: {type(exc).__name__}",
        }
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return {
            "ok":     False,
            "reason": "json decode error",
        }
    if not isinstance(doc, dict):
        return {
            "ok":     False,
            "reason": "root is not a JSON object",
        }
    missing: list[str] = []
    for field in _CHECKLIST_REQUIRED_ARTIFACT_FIELDS:
        value = doc.get(field)
        if not isinstance(value, str) or not value.strip():
            missing.append(field)
        elif (
            field == "mechanism_family"
            and value.strip().lower()
            == _CHECKLIST_MECHANISM_FAMILY_NONE_SENTINEL
        ):
            missing.append(f"{field}=none-sentinel")
    if missing:
        return {
            "ok":     False,
            "reason": "missing required fields: " + ", ".join(missing),
        }
    return {"ok": True, "reason": ""}


def _check_record(
    *,
    check_id:    str,
    description: str,
    required:    bool,
    status:      str,
    evidence:    list[str],
    next_action: str,
) -> dict[str, Any]:
    return {
        "check_id":    check_id,
        "description": description,
        "required":    bool(required),
        "status":      status,
        "evidence":    list(evidence),
        "next_action": next_action,
    }


def _classify_readiness(
    *,
    blockers:           list[dict[str, Any]],
    partial:            list[dict[str, Any]],
    required_check_ids: set[str],
) -> str:
    """Pick a readiness status from the per-check verdicts.

    Conservative by construction:

    * Any required check in ``blockers`` → ``"blocked"``.
    * Else, any required check in ``partial`` → ``"required_checks_pending"``.
    * Else → ``"required_checks_passed"``.

    The strongest claim this function emits is
    ``"required_checks_passed"``.  It never emits a flat
    ``"demo_ready"`` token — the demo decision stays with the
    operator.
    """
    def _has_required(items: list[dict[str, Any]]) -> bool:
        for c in items:
            if (
                c.get("required") is True
                and c.get("check_id") in required_check_ids
            ):
                return True
        return False

    if _has_required(blockers):
        return _READINESS_BLOCKED
    if _has_required(partial):
        return _READINESS_PENDING
    return _READINESS_PASSED


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Section C demo-readiness checklist", ""]
    lines.append(f"OK:                {report['ok']}")
    lines.append(f"Readiness status:  {report['readiness_status']}")
    lines.append("")
    lines.append(f"Passed   ({len(report['passed_checks'])}):")
    for c in report["passed_checks"]:
        if isinstance(c, dict):
            lines.append(f"  - {c.get('check_id')}")
    lines.append("")
    lines.append(f"Partial  ({len(report['partial_checks'])}):")
    for c in report["partial_checks"]:
        if isinstance(c, dict):
            lines.append(f"  - {c.get('check_id')}")
            lines.append(f"      next_action: {c.get('next_action')}")
    lines.append("")
    lines.append(f"Blockers ({len(report['blockers'])}):")
    for c in report["blockers"]:
        if isinstance(c, dict):
            lines.append(f"  - {c.get('check_id')}")
            lines.append(f"      next_action: {c.get('next_action')}")
    if report.get("required_before_demo"):
        lines.append("")
        lines.append("Required before demo:")
        for a in report["required_before_demo"]:
            lines.append(f"  - {a}")
    if report.get("optional_before_demo"):
        lines.append("")
        lines.append("Optional before demo:")
        for a in report["optional_before_demo"]:
            lines.append(f"  - {a}")
    if report.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for w in report["warnings"]:
            lines.append(f"  - {w}")
    if report.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for e in report["errors"]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Section C demo-readiness checklist.  Walks "
            "six narrow checks against the repo today and reports "
            "which are passed, partial, or blocked.  Never mutates "
            "an artifact; never connects to a DB; never imports "
            "FastAPI; never claims demo readiness on its own — "
            "the operator owns the final approval."
        ),
    )
    parser.add_argument(
        "--repo-root", dest="repo_root", default=None,
        help=(
            "Path to the repository root.  Defaults to the parent "
            "of this script.  Read-only."
        ),
    )
    parser.add_argument(
        "--freeze-artifact", dest="freeze_artifact", default=None,
        help=(
            f"Path to the freeze-candidate evidence artifact.  "
            f"Defaults to {_DEFAULT_FREEZE_ARTIFACT!r} under the "
            f"repo root.  Read-only."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text checklist.",
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the checklist has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_section_c_demo_readiness_checklist(
        repo_root=args.repo_root,
        freeze_artifact=args.freeze_artifact,
        output_path=args.output_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_section_c_demo_readiness_checklist",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
