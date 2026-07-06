"""Mission I1 — ordinary-period candidate-universe and funnel builder.

Mechanical execution of the frozen Mission I0 protocol
(stats/I0_ORDINARY_PERIOD_BASELINE_PROTOCOL.md, ``i0-v1``).  This module answers
one question only: did the code construct exactly the ordinary-date reference
universes, exclusion sets, and denominator funnels frozen in I0?

It computes NO substantive event-versus-ordinary comparison — no MEMP, no
percentile ranks, no calibration placements, no returns.  Everything here is
date / session-index / count geometry.  **No arithmetic is performed on price
close values**: the shipped price cache is read only to decide whether a valid
adjusted (or raw) close row exists for a session, never to read its value.

Reuse, not reimplementation.  The eligibility primitives come straight from the
shipped event-study gate (``event_study_validation``): the estimation window,
the last-index-on-or-before anchor resolver, and the interior-contiguity guard.
The gate itself hard-codes a 20-session forward requirement for every horizon,
so it cannot be called directly for a per-horizon funnel; instead this module
reuses those exact primitives and applies I0 §7.4's per-horizon forward rule.
``tests/test_i1_candidate_universe.py::GateEquivalenceTest`` pins that the
decomposition agrees with the shipped gate at the 20-session horizon.

Read-only.  The substrate is the gitignored ``g3_price_cache.db`` (the same
Yahoo refetch the G3 grinder used); ``events.db`` is not required.  Nothing is
written except, by the caller, the tracked Markdown report.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import db as _db
import event_study_validation as esv
from scripts import g_state_acquisition as gsa

# ---------------------------------------------------------------------------
# Frozen I0 constants (i0-v1).
# ---------------------------------------------------------------------------

I1_VERSION = "i1-candidate-universe-v1"
I0_PROTOCOL = "i0-v1"

ERA_START = "2018-01-01"
ERA_END = "2025-12-31"
HORIZONS = (1, 5, 20)
ESTIMATION_WINDOW = esv.ESTIMATION_WINDOW  # 60 prior joint sessions

# Reproducibility pins (I0 §18) — fail loud if the substrate drifted.
PINNED_JOINT_SESSIONS = 2385
PINNED_ERA_SESSIONS = 2011

ROOT = Path(__file__).resolve().parents[1]
G1A_PATH = ROOT / "stats" / "G1A_FOMC_FRAME_INVENTORY.md"
G1B_PATH = ROOT / "stats" / "G1B_OPEC_DESIGNED_RESERVOIR.md"

# The OPEC known-date exclusion register (I0 §8,
# ``opec-known-date-exclusion-register@i0-v1``) is a curated union: the 38
# dated source records of the G1B discovery ledger PLUS three hand-named dates
# that live in I0/G1B prose, not in the ledger table.  There is no single
# mechanical rule that yields all 41 — the three are enumerated exceptions, so
# they are declared here as a cited constant (parsing them out of prose would
# be more fragile, not less).  Their citations, and the no-double-count /
# 38+3=41 / 41→39-anchor reconciliation, are pinned by the register tests.
#   * 2020-03-06 — the OPEC+/Russia break context date (G1B D09 discussion).
#   * 2022-12-04 — a named non-material meeting (G1B §1), NOT a promoted event.
#   * 2025-05-28 — a named non-material meeting (G1B §1), NOT a promoted event.
OPEC_REGISTER_EXTRAS = ("2020-03-06", "2022-12-04", "2025-05-28")


@dataclass(frozen=True)
class LaneSpec:
    """A study lane: primary asset, market benchmark, sector benchmark."""

    key: str
    primary: str
    benchmark: str
    sector: str
    study_denominator: int
    study_source: str  # G1A / G1B ledger path key
    exclusion_kind: str


FOMC_SPEC = LaneSpec("FOMC", "KRE", "SPY", "XLF", 65, "G1A", "study_frame")
OPEC_SPEC = LaneSpec("OPEC", "XOP", "SPY", "XLE", 32, "G1B", "known_date_register")
SPECS = (FOMC_SPEC, OPEC_SPEC)


def default_db_path() -> Path:
    """The gitignored G3 price-cache substrate (read-only)."""
    return gsa.CACHE_DIR / "g3_price_cache.db"


# ---------------------------------------------------------------------------
# Read-only cache access (existence + basis only — never a close value).
# ---------------------------------------------------------------------------


def _adjusted_dates(ticker: str, db_path: Path) -> set[str]:
    saved = _db.DB_FILE
    _db.DB_FILE = str(db_path)
    try:
        return set(esv._read_closes(ticker, auto_adjust=True))
    finally:
        _db.DB_FILE = saved


def _raw_dates(ticker: str, db_path: Path) -> set[str]:
    saved = _db.DB_FILE
    _db.DB_FILE = str(db_path)
    try:
        return set(esv._read_closes(ticker, auto_adjust=False))
    finally:
        _db.DB_FILE = saved


def adjusted_joint_frame(spec: LaneSpec, db_path: Path | None = None) -> list[str]:
    """Sorted intersection of adjusted sessions across all three lane series.

    The triple joint (primary ∩ benchmark ∩ sector) is the single denominator
    frame; F3's adjusted basis is preferred and — because raw coverage is
    identical (zero raw-only sessions, see :func:`raw_only_count`) — uniformly
    available, so no cross-basis pairing ever occurs.
    """
    db_path = db_path or default_db_path()
    a = _adjusted_dates(spec.primary, db_path)
    b = _adjusted_dates(spec.benchmark, db_path)
    c = _adjusted_dates(spec.sector, db_path)
    return sorted(a & b & c)


def raw_only_count(spec: LaneSpec, db_path: Path | None = None) -> int:
    """Sessions in the raw triple-joint frame that are not adjusted-available."""
    db_path = db_path or default_db_path()
    raw = (_raw_dates(spec.primary, db_path)
           & _raw_dates(spec.benchmark, db_path)
           & _raw_dates(spec.sector, db_path))
    adj = set(adjusted_joint_frame(spec, db_path))
    return len(raw - adj)


def verify_pins(n_joint: int, n_era: int) -> None:
    """Refuse to run if the substrate frame counts don't reconcile (I0 §18)."""
    if n_joint != PINNED_JOINT_SESSIONS:
        raise RuntimeError(
            f"joint-session pin broken: got {n_joint}, "
            f"expected {PINNED_JOINT_SESSIONS} — substrate drifted, refusing")
    if n_era != PINNED_ERA_SESSIONS:
        raise RuntimeError(
            f"era-session pin broken: got {n_era}, "
            f"expected {PINNED_ERA_SESSIONS} — substrate drifted, refusing")


def era_indices(frame: list[str]) -> list[int]:
    """Frame indices whose session falls inside the 2018–2025 era window."""
    return [i for i, d in enumerate(frame) if ERA_START <= d <= ERA_END]


def session_index(frame: list[str], iso: str) -> int | None:
    """Largest frame index whose session is on or before ``iso`` (I0 anchor)."""
    return esv._last_index_le(frame, iso)


def resolve_anchor_indices(frame: list[str], dates) -> list[int]:
    """Sorted unique anchor sessions for a set of calendar dates."""
    out = set()
    for d in dates:
        idx = session_index(frame, d)
        if idx is None:
            raise RuntimeError(f"exclusion date {d} precedes the joint frame")
        out.add(idx)
    return sorted(out)


def interior_gap_ok(frame: list[str], idx: int, h: int) -> bool:
    """True iff the estimation..forward window for horizon ``h`` is contiguous.

    Reuses the shipped ``_is_contiguous`` guard (>5 calendar-day interior gap →
    excluded), applied to the per-horizon window ``[idx-60 .. idx+h]``.
    """
    window = frame[idx - ESTIMATION_WINDOW: idx + h + 1]
    return esv._is_contiguous(window)


def is_preexclusion_eligible(frame: list[str], idx: int, h: int) -> bool:
    """Estimation + forward + interior-gap eligibility (before exclusion).

    This is the per-horizon decomposition of the shipped gate's structural
    checks: ``idx >= ESTIMATION_WINDOW`` (≥60 prior joint sessions),
    ``idx + h <= len-1`` (≥h forward joint sessions), and interior contiguity.
    """
    n = len(frame)
    if idx < ESTIMATION_WINDOW:
        return False
    if idx + h > n - 1:
        return False
    return interior_gap_ok(frame, idx, h)


def canonical_non_overlapping_windows(indices, h: int) -> list[int]:
    """The canonical maximal set of disjoint response windows on ``indices``.

    A response window is ``[t, t+h]`` (I0 §8): it spans the sessions
    ``t, t+1, …, t+h``.  Two windows ``[t, t+h]`` and ``[t', t'+h]`` **share a
    session** iff ``|t - t'| <= h`` — at distance exactly ``h`` they meet at a
    shared endpoint, which is still overlap under the frozen "shares no
    session" semantics (the same buffer that makes the exclusion rule drop
    ``|i - e| <= h``).  Two windows are therefore disjoint iff their starts are
    at least ``h + 1`` sessions apart.

    Selection is the deterministic greedy earliest-first packing (starting at
    the first eligible session, matching the §15 anchor): take the earliest
    start, then repeatedly take the earliest remaining start at least ``h + 1``
    beyond the last one taken.  For same-length windows this greedy is optimal
    (it returns a maximum-size set of pairwise-disjoint windows), and it is the
    single canonical non-overlapping subset — the block count is its size and
    the §15 F3 decimation, when implemented in I2, must consume this same
    subset (not a rank-based "every h-th eligible session", which ignores
    exclusion holes and endpoint sharing).

    This replaces ``eligible_count // h``, which is not a window count at all:
    at ``h = 1`` it returns the entire eligible count (windows that pervasively
    overlap), and it ignores the actual session indices, so exclusion holes
    make it both over- and under-state the true disjoint count.
    """
    picks: list[int] = []
    last: int | None = None
    for i in sorted(indices):
        if last is None or i >= last + h + 1:
            picks.append(i)
            last = i
    return picks


# ---------------------------------------------------------------------------
# Ledger parsing (study universes + OPEC register).
# ---------------------------------------------------------------------------


def parse_fomc_frame_dates(path: Path | None = None) -> list[str]:
    """The complete 65-event FOMC frame (study denominator AND exclusion set)."""
    rows = gsa.parse_g1a_candidates(str(path or G1A_PATH))
    return sorted({r["event_date"] for r in rows})


def parse_opec_study_dates(path: Path | None = None) -> list[str]:
    """The 32 promoted OPEC identities (study denominator only)."""
    rows = gsa.parse_g1b_candidates(str(path or G1B_PATH))
    return sorted({r["event_date"] for r in rows})


_DISCOVERY_ROW = re.compile(r"^\|\s*D\d{2}\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|")


def parse_opec_discovery_source_dates(path: Path | None = None) -> list[str]:
    """The 38 dated source records of the G1B discovery ledger (§2 table)."""
    text = (path or G1B_PATH).read_text(encoding="utf-8")
    dates = []
    for line in text.splitlines():
        m = _DISCOVERY_ROW.match(line)
        if m:
            dates.append(m.group(1))
    return dates


@dataclass(frozen=True)
class OpecRegister:
    """The 41-date OPEC known-date exclusion register (contamination control)."""

    discovery_source_dates: tuple[str, ...]
    extras: tuple[str, ...]
    dates: tuple[str, ...]


def build_opec_register(path: Path | None = None) -> OpecRegister:
    discovery = parse_opec_discovery_source_dates(path)
    extras = tuple(OPEC_REGISTER_EXTRAS)
    dates = tuple(sorted(set(discovery) | set(extras)))
    return OpecRegister(
        discovery_source_dates=tuple(discovery), extras=extras, dates=dates)


# ---------------------------------------------------------------------------
# Funnel construction (sequential sieve, I0 §17 order).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FunnelCell:
    lane: str
    horizon: int
    era_count: int
    estimation_casualties: int
    forward_casualties: int
    gap_casualties: int
    exclusion_casualties: int
    final_count: int
    feasible: bool
    status: str
    block_count: int
    per_year: dict[str, int]
    candidate_indices: tuple[int, ...]


def build_funnel_cell(spec: LaneSpec, frame: list[str], era: list[int],
                      anchors: list[int], h: int) -> FunnelCell:
    n = len(frame)
    anchor_set = anchors  # small; linear proximity scan below

    # Sequential sieve in I0 §17 order: era → estimation → forward → gap →
    # exclusion.  Each stage runs on the prior stage's survivors so that
    # "input − casualties = survivors" reconciles by construction.
    est = [i for i in era if i >= ESTIMATION_WINDOW]
    est_cas = len(era) - len(est)

    fwd = [i for i in est if i + h <= n - 1]
    fwd_cas = len(est) - len(fwd)

    gap = [i for i in fwd if interior_gap_ok(frame, i, h)]
    gap_cas = len(fwd) - len(gap)

    final = [i for i in gap
             if not any(abs(i - e) <= h for e in anchor_set)]
    excl_cas = len(gap) - len(final)

    per_year: dict[str, int] = {}
    for i in final:
        y = frame[i][:4]
        per_year[y] = per_year.get(y, 0) + 1

    feasible = len(final) > 0
    status = "feasible" if feasible else "structurally_infeasible"
    return FunnelCell(
        lane=spec.key,
        horizon=h,
        era_count=len(era),
        estimation_casualties=est_cas,
        forward_casualties=fwd_cas,
        gap_casualties=gap_cas,
        exclusion_casualties=excl_cas,
        final_count=len(final),
        feasible=feasible,
        status=status,
        block_count=len(canonical_non_overlapping_windows(final, h)),
        per_year=dict(sorted(per_year.items())),
        candidate_indices=tuple(final),
    )


@dataclass(frozen=True)
class LaneResult:
    key: str
    primary: str
    benchmark: str
    sector: str
    joint_sessions: list[str]
    era_indices: list[int]
    raw_only_sessions: int
    study_denominator: int
    study_event_dates: list[str]
    exclusion_kind: str
    exclusion_dates: list[str]
    exclusion_anchor_indices: list[int]
    cells: dict[int, FunnelCell]
    register: OpecRegister | None = None


def build_lane(spec: LaneSpec, db_path: Path | None = None) -> LaneResult:
    frame = adjusted_joint_frame(spec, db_path)
    era = era_indices(frame)
    verify_pins(len(frame), len(era))

    if spec.key == "FOMC":
        study = parse_fomc_frame_dates()
        exclusion_dates = list(study)  # exclusion set == complete 65-frame
        register = None
    else:
        study = parse_opec_study_dates()
        register = build_opec_register()
        exclusion_dates = list(register.dates)

    anchors = resolve_anchor_indices(frame, exclusion_dates)
    cells = {h: build_funnel_cell(spec, frame, era, anchors, h) for h in HORIZONS}

    return LaneResult(
        key=spec.key,
        primary=spec.primary,
        benchmark=spec.benchmark,
        sector=spec.sector,
        joint_sessions=frame,
        era_indices=era,
        raw_only_sessions=raw_only_count(spec, db_path),
        study_denominator=len(study),
        study_event_dates=sorted(study),
        exclusion_kind=spec.exclusion_kind,
        exclusion_dates=sorted(exclusion_dates),
        exclusion_anchor_indices=anchors,
        cells=cells,
        register=register,
    )


def build_universe(db_path: Path | None = None) -> dict[str, LaneResult]:
    return {spec.key: build_lane(spec, db_path) for spec in SPECS}


# ---------------------------------------------------------------------------
# Deterministic, timestamp-free Markdown report.
# ---------------------------------------------------------------------------


def _cell_row(c: FunnelCell) -> str:
    return (f"| {c.horizon}d | {c.era_count} | {c.estimation_casualties} | "
            f"{c.forward_casualties} | {c.gap_casualties} | "
            f"{c.exclusion_casualties} | **{c.final_count}** | "
            f"{c.block_count} | {c.status} |")


def _per_year_line(cells: dict[int, FunnelCell]) -> list[str]:
    years = sorted({y for c in cells.values() for y in c.per_year})
    header = "| horizon | " + " | ".join(years) + " |"
    sep = "|" + "---|" * (len(years) + 1)
    lines = [header, sep]
    for h in HORIZONS:
        c = cells[h]
        row = "| {}d | ".format(h) + " | ".join(
            str(c.per_year.get(y, 0)) for y in years) + " |"
        lines.append(row)
    return lines


def render_report(universe: dict[str, LaneResult]) -> str:
    L: list[str] = []
    L.append("# I1 — Ordinary-Period Candidate Universe and Funnel")
    L.append("")
    L.append(f"Version `{I1_VERSION}` — mechanical execution of the frozen "
             f"`{I0_PROTOCOL}` baseline protocol "
             "(`stats/I0_ORDINARY_PERIOD_BASELINE_PROTOCOL.md`).")
    L.append("")
    L.append("This report records **only** how the ordinary-date reference "
             "universes, exclusion sets, and denominator funnels were "
             "constructed. It does **not** compute the event-versus-ordinary "
             "comparison, and reads no price close values — every number below "
             "is a date, a session index, or a count.")
    L.append("")
    L.append("The two families keep entirely separate ledgers: their "
             "denominators, exclusion sets, and funnels are never pooled.")
    L.append("")

    for key in ("FOMC", "OPEC"):
        lane = universe[key]
        L.append(f"## {key} lane")
        L.append("")
        L.append(f"- Primary asset `{lane.primary}`; market benchmark "
                 f"`{lane.benchmark}`; sector benchmark `{lane.sector}`.")
        L.append(f"- Joint (triple-intersection) sessions: "
                 f"**{len(lane.joint_sessions)}** "
                 f"(`{lane.joint_sessions[0]}` → `{lane.joint_sessions[-1]}`); "
                 f"era 2018–2025 sessions: **{len(lane.era_indices)}**.")
        L.append(f"- Raw-only sessions (adjusted basis unavailable): "
                 f"**{lane.raw_only_sessions}** — F3 basis is uniformly "
                 "adjusted, no cross-basis pairing.")
        L.append(f"- Study denominator (promoted events): "
                 f"**{lane.study_denominator}**.")
        if key == "OPEC":
            reg = lane.register
            L.append(f"- Known-date exclusion register "
                     f"(`opec-known-date-exclusion-register@{I0_PROTOCOL}`): "
                     f"**{len(reg.dates)}** calendar dates "
                     f"= {len(reg.discovery_source_dates)} discovery-ledger "
                     f"source records + {len(reg.extras)} named "
                     f"non-ledger dates "
                     f"(`{'`, `'.join(reg.extras)}`) → "
                     f"**{len(lane.exclusion_anchor_indices)}** anchor "
                     "sessions.")
            L.append("  The register is a contamination-control set. Its dates "
                     "are **never** study-denominator members: the OPEC study "
                     f"sample stays exactly **{lane.study_denominator}** "
                     "promoted identities, and the register is **not** added "
                     "to it.")
        else:
            L.append(f"- Exclusion set: the complete "
                     f"{lane.study_denominator}-event frame "
                     f"→ **{len(lane.exclusion_anchor_indices)}** anchor "
                     "sessions.")
        L.append("")
        L.append("| horizon | era | est cut | fwd cut | gap cut | "
                 "excl cut | eligible | non-overlap blocks | status |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for h in HORIZONS:
            L.append(_cell_row(lane.cells[h]))
        L.append("")
        L.append("Funnel order (I0 §17): era → estimation (≥60 prior) → "
                 "forward (≥h ahead) → interior-gap → known-date exclusion; "
                 "each stage sieves the prior survivors, so "
                 "era − cuts = eligible at every horizon. The non-overlap "
                 "block count is the size of the canonical set of disjoint "
                 "response windows `[t, t+h]` — a deterministic greedy "
                 "earliest-first packing on the eligible session indices, "
                 "where two windows share no session only if their starts are "
                 "at least `h+1` apart (I0 §8; a shared endpoint at distance "
                 "`h` is overlap). It is **not** `eligible // h` (which ignores "
                 "index positions and, at `h=1`, returns the full count), and "
                 "**not** an independent, effective, or degrees-of-freedom "
                 "sample size.")
        L.append("")
        if key == "FOMC":
            L.append("The 20d horizon is **structurally infeasible**: with the "
                     "estimation and forward gates removing nothing in-era, "
                     "the exclusion geometry alone leaves zero eligible "
                     "sessions — a pre-declared calendar fact (I0 §8), not a "
                     "data gap and not rescued by any substitute date.")
            L.append("")
        L.append("Eligible-session count by year:")
        L.append("")
        L.extend(_per_year_line(lane.cells))
        L.append("")

    L.append("---")
    L.append("")
    L.append("Reproducibility: joint-session and era pins "
             f"({PINNED_JOINT_SESSIONS} / {PINNED_ERA_SESSIONS} per lane) are "
             "fail-loud; the builder refuses to run if the substrate frame "
             "counts do not reconcile. Substrate: the gitignored "
             "`g3_price_cache.db` (Yahoo refetch; drift disclosed). "
             "Event universes come from the tracked G1 ledgers.")
    L.append("")
    return "\n".join(L)


def emit_report(report: str, stream=None) -> None:
    """Write the report to ``stream`` (default stdout) as UTF-8, verbatim.

    The report is a deterministic UTF-8 document that uses characters such as
    ``→`` (U+2192) and ``≥`` (U+2265).  On Windows the console's text stdout
    defaults to a legacy code page (cp1252) that cannot encode them, so a plain
    ``print`` raises ``UnicodeEncodeError`` — the shipped emit defect.  Writing
    the UTF-8 bytes straight to the underlying binary buffer bypasses that
    locale text layer, so the emit succeeds without the operator setting
    ``PYTHONUTF8`` / ``PYTHONIOENCODING``.  A stream that exposes no binary
    ``.buffer`` (e.g. an in-memory text capture) receives the string directly.
    The emitted bytes are exactly ``render_report()`` encoded as UTF-8 — the
    report content is unchanged.
    """
    stream = sys.stdout if stream is None else stream
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(report.encode("utf-8"))
        buffer.flush()
    else:
        stream.write(report)


if __name__ == "__main__":  # pragma: no cover
    emit_report(render_report(build_universe()))
