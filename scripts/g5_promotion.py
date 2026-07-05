"""G5 - controlled promotion of Mission G historical evidence.

Mission G, protocol g0-v1, promotion version g5-promotion-v1.

Promotes the 97 frozen historical candidates (65 frame-complete FOMC + 32
designed-contrast OPEC) into the shared storage substrate (`events.db`)
while preserving SEPARATE denominator ledgers (protocol section 2).

Storage design (smallest additive implementation): one new dedicated table
`g_historical_evidence`, one row per candidate, every row carrying its
denominator ledger, sampling family, provenance, frozen transmission
mapping + version, point-in-time state values + availability, and the
frozen G4 tags + freeze version. The table enters NO existing query path:
the accepted track record, its stage-driven surfaces, `event_hygiene`, and
every other pre-existing table are never read for writing and never
written. The events table is consulted READ-ONLY for the ledger-precedence
collision gate (a candidate identity already present as a live row would
count in the live ledger and must halt promotion loudly).

Firewall: the schema carries no outcome-shaped and no mechanism-taxonomy
column; row validation rejects unexpected keys, null primary states,
mapping drift, ledger/family mismatch, tag/state inconsistency, and any
credit availability mismatch. Promotion is one transaction - idempotent on
identical rerun, full rollback on any failure, never a row-level patch.

Usage:

    python scripts/g5_promotion.py --temp-proof PATH   # proof on a copy
    python scripts/g5_promotion.py --live              # promote events.db
    python scripts/g5_promotion.py --verify [PATH]     # read-only probe
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import g_state_acquisition as gsa  # noqa: E402
from scripts import g4_structural_freeze as g4  # noqa: E402
from scripts.g3_mechanical_grinder import (  # noqa: E402
    MAPPING_VERSION, TRANSMISSION_MAP)

PROMOTION_VERSION = "g5-promotion-v1"
GTABLE = "g_historical_evidence"
LIVE_DB = ROOT / "events.db"

ACCEPTED_STAGES = ("realized", "anticipation", "de-escalation",
                   "escalation", "normalization")

LEDGERS = ("frame_complete_historical", "designed_contrast")
_FAMILY_TO_LEDGER = {"fomc": "frame_complete_historical",
                     "opec": "designed_contrast"}

# Exact schema whitelist: state INPUTS, identity, provenance, frozen
# mapping and tags. No outcome-shaped column, no mechanism-taxonomy column.
G_COLUMNS = (
    "candidate_id", "denominator_ledger", "sampling_family",
    "source_provenance", "event_date", "cutoff", "mapping_version",
    "primary_asset", "market_benchmark", "sector_benchmark",
    "freeze_version",
    "state_fed_policy_path", "state_vix_level_percentile",
    "state_spy_trend_ma200", "state_curve_2s10s", "state_credit_hy_oas",
    "credit_availability",
    "tag_fed_policy_path", "tag_spy_trend_ma200", "tag_curve_2s10s",
)

_PRIMARY_STATE_COLUMNS = ("state_fed_policy_path",
                          "state_vix_level_percentile",
                          "state_spy_trend_ma200", "state_curve_2s10s")

_TAG_VALUES = {
    "tag_fed_policy_path": ("easing", "hold", "tightening"),
    "tag_spy_trend_ma200": ("below_ma", "above_ma"),
    "tag_curve_2s10s": ("inverted", "non_inverted"),
}

_TAG_STATE_COLUMN = {
    "tag_fed_policy_path": ("state_fed_policy_path", "fed_policy_path"),
    "tag_spy_trend_ma200": ("state_spy_trend_ma200", "spy_trend_ma200"),
    "tag_curve_2s10s": ("state_curve_2s10s", "curve_2s10s"),
}

_FORBIDDEN_KEY_TOKENS = frozenset({
    "abnormal", "outcome", "sar", "car", "scar", "return", "returns",
    "sign", "direction", "effect", "magnitude", "readout", "reaction",
    "response", "label", "mechanism", "taxonomy", "overlay", "j1",
})

# Family-identity patterns for the read-only ledger-precedence collision
# gate against live events rows (LIKE, case-insensitive via lower()).
_FAMILY_HEADLINE_PATTERNS = {
    "fomc": ("%fomc%", "%federal reserve%", "%target range%"),
    "opec": ("%opec%",),
}

_CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {GTABLE} (
    candidate_id TEXT PRIMARY KEY,
    denominator_ledger TEXT NOT NULL CHECK (denominator_ledger IN
        ('frame_complete_historical', 'designed_contrast')),
    sampling_family TEXT NOT NULL CHECK (sampling_family IN
        ('fomc', 'opec')),
    source_provenance TEXT NOT NULL,
    event_date TEXT NOT NULL UNIQUE,
    cutoff TEXT NOT NULL,
    mapping_version TEXT NOT NULL,
    primary_asset TEXT NOT NULL,
    market_benchmark TEXT NOT NULL,
    sector_benchmark TEXT NOT NULL,
    freeze_version TEXT NOT NULL,
    state_fed_policy_path REAL NOT NULL,
    state_vix_level_percentile REAL NOT NULL,
    state_spy_trend_ma200 REAL NOT NULL,
    state_curve_2s10s REAL NOT NULL,
    state_credit_hy_oas REAL,
    credit_availability TEXT NOT NULL CHECK (credit_availability IN
        ('available', 'source_missing')),
    tag_fed_policy_path TEXT NOT NULL CHECK (tag_fed_policy_path IN
        ('easing', 'hold', 'tightening')),
    tag_spy_trend_ma200 TEXT NOT NULL CHECK (tag_spy_trend_ma200 IN
        ('below_ma', 'above_ma')),
    tag_curve_2s10s TEXT NOT NULL CHECK (tag_curve_2s10s IN
        ('inverted', 'non_inverted'))
)
"""


# ---------------------------------------------------------------------------
# Row validation (pure; shared by tests, temp proof, and live promotion)
# ---------------------------------------------------------------------------


def _classify(dim: str, value: float) -> str:
    return g4._SIGN_TAG_RULES[dim]["classify"](value)


def validate_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    """Every promotion invariant that is checkable without a database."""
    seen_ids: set[str] = set()
    seen_dates: set[str] = set()
    for row in rows:
        for key in row:
            if key not in G_COLUMNS:
                tokens = set(str(key).lower().replace("-", "_").split("_"))
                hit = tokens & _FORBIDDEN_KEY_TOKENS
                if hit:
                    kind = ("mechanism-taxonomy"
                            if hit & {"mechanism", "taxonomy", "overlay",
                                      "j1"} else "outcome")
                    raise ValueError(
                        f"{kind}-shaped key {key!r} rejected by the G5 "
                        "promotion firewall")
                raise ValueError(f"unexpected key {key!r}: promotion "
                                 "accepts only the whitelisted G columns")
        missing = [c for c in G_COLUMNS if c not in row]
        if missing:
            raise ValueError(f"row {row.get('candidate_id')!r} missing "
                             f"columns {missing}")
        cid = row["candidate_id"]
        if cid in seen_ids:
            raise ValueError(f"duplicate candidate_id {cid!r}")
        seen_ids.add(cid)
        if row["event_date"] in seen_dates:
            raise ValueError(f"duplicate event_date {row['event_date']!r}")
        seen_dates.add(row["event_date"])

        fam = row["sampling_family"]
        if _FAMILY_TO_LEDGER.get(fam) != row["denominator_ledger"]:
            raise ValueError(
                f"{cid}: ledger {row['denominator_ledger']!r} is not the "
                f"ledger of family {fam!r} - frame rows may not enter the "
                "designed ledger and designed rows may not enter the frame "
                "ledger")
        lens = TRANSMISSION_MAP[fam]
        if (row["primary_asset"], row["market_benchmark"],
                row["sector_benchmark"]) != (lens.primary, lens.market,
                                             lens.sector):
            raise ValueError(
                f"{cid}: assets do not match the frozen transmission map "
                f"for {fam!r}")
        if row["mapping_version"] != MAPPING_VERSION:
            raise ValueError(f"{cid}: mapping_version "
                             f"{row['mapping_version']!r} != frozen "
                             f"{MAPPING_VERSION!r}")
        for col in _PRIMARY_STATE_COLUMNS:
            if row[col] is None:
                raise ValueError(f"{cid}: primary state {col} is null; "
                                 "the frozen primary vector is complete "
                                 "for every candidate")
        has_credit = row["state_credit_hy_oas"] is not None
        want = "available" if has_credit else "source_missing"
        if row["credit_availability"] != want:
            raise ValueError(
                f"{cid}: credit_availability "
                f"{row['credit_availability']!r} inconsistent with value "
                f"presence (expected {want!r})")
        for tag_col, allowed in _TAG_VALUES.items():
            if row[tag_col] not in allowed:
                raise ValueError(f"{cid}: {tag_col} value "
                                 f"{row[tag_col]!r} not in {allowed}")
            state_col, dim = _TAG_STATE_COLUMN[tag_col]
            expected = _classify(dim, row[state_col])
            if row[tag_col] != expected:
                raise ValueError(
                    f"{cid}: tag {tag_col}={row[tag_col]!r} inconsistent "
                    f"with state {state_col}={row[state_col]} (frozen "
                    f"rule gives {expected!r})")


# ---------------------------------------------------------------------------
# Ledger-precedence collision gate (read-only on events)
# ---------------------------------------------------------------------------


def find_live_collisions(con: sqlite3.Connection,
                         rows: Sequence[Mapping[str, Any]]
                         ) -> list[dict[str, Any]]:
    collisions = []
    for row in rows:
        for pattern in _FAMILY_HEADLINE_PATTERNS[row["sampling_family"]]:
            hits = con.execute(
                "SELECT id, headline, stage FROM events "
                "WHERE event_date = ? AND lower(headline) LIKE ?",
                (row["event_date"], pattern)).fetchall()
            for hit in hits:
                collisions.append({
                    "candidate_id": row["candidate_id"],
                    "event_date": row["event_date"],
                    "events_id": hit[0],
                    "events_stage": hit[2],
                })
    return collisions


# ---------------------------------------------------------------------------
# Promotion (one transaction; idempotent; full rollback)
# ---------------------------------------------------------------------------


def promote(db_path: Path | str,
            rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    validate_rows(rows)
    con = sqlite3.connect(db_path)
    try:
        con.execute("BEGIN")
        con.execute(_CREATE_TABLE)
        collisions = find_live_collisions(con, rows)
        if collisions:
            raise ValueError(
                "ledger-precedence collision: candidate identity already "
                "present as a live events row; promotion halted for all "
                f"rows: {json.dumps(collisions, sort_keys=True)}")
        inserted = 0
        already = 0
        for row in rows:
            existing = con.execute(
                f"SELECT * FROM {GTABLE} WHERE candidate_id = ?",
                (row["candidate_id"],)).fetchone()
            if existing is not None:
                stored = dict(zip(G_COLUMNS, existing))
                incoming = {c: row[c] for c in G_COLUMNS}
                if stored != incoming:
                    diff = [c for c in G_COLUMNS
                            if stored[c] != incoming[c]]
                    raise ValueError(
                        f"{row['candidate_id']}: existing promoted row "
                        f"differs on {diff}; promotion never updates a "
                        "stored row")
                already += 1
                continue
            con.execute(
                f"INSERT INTO {GTABLE} ({', '.join(G_COLUMNS)}) VALUES "
                f"({', '.join('?' for _ in G_COLUMNS)})",
                tuple(row[c] for c in G_COLUMNS))
            inserted += 1
        by_ledger: dict[str, int] = {}
        for ledger, n in con.execute(
                f"SELECT denominator_ledger, COUNT(*) FROM {GTABLE} "
                "GROUP BY denominator_ledger"):
            by_ledger[ledger] = n
        con.commit()
        return {"promotion_version": PROMOTION_VERSION,
                "inserted": inserted, "already_present": already,
                "by_ledger": dict(sorted(by_ledger.items()))}
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Read-only verification battery
# ---------------------------------------------------------------------------


def accepted_track_record_count(db_path: Path | str) -> int:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        placeholders = ", ".join("?" for _ in ACCEPTED_STAGES)
        return con.execute(
            f"SELECT COUNT(*) FROM events WHERE stage IN ({placeholders}) "
            "AND id NOT IN (SELECT event_id FROM event_hygiene "
            "WHERE override_class = 'synthetic_seed')",
            ACCEPTED_STAGES).fetchone()[0]
    finally:
        con.close()


def table_dump_hashes(db_path: Path | str,
                      exclude: Sequence[str] = (GTABLE,)
                      ) -> dict[str, str]:
    """Canonical per-table content hash for every non-excluded table."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "ORDER BY name")]
        out: dict[str, str] = {}
        for t in tables:
            if t in exclude:
                continue
            h = hashlib.sha256()
            for row in con.execute(f"SELECT * FROM [{t}] ORDER BY rowid"):
                h.update(repr(row).encode("utf-8"))
            out[t] = h.hexdigest()
        return out
    finally:
        con.close()


def verify_promotion(db_path: Path | str) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        q = lambda sql, *p: con.execute(sql, p).fetchall()  # noqa: E731
        total = q(f"SELECT COUNT(*) FROM {GTABLE}")[0][0]
        by_ledger = dict(q(f"SELECT denominator_ledger, COUNT(*) FROM "
                           f"{GTABLE} GROUP BY denominator_ledger"))
        by_mapping = {f"{r[0]}/{r[1]}/{r[2]}/{r[3]}": r[4] for r in q(
            f"SELECT sampling_family, primary_asset, market_benchmark, "
            f"sector_benchmark, COUNT(*) FROM {GTABLE} GROUP BY 1,2,3,4")}
        tag_occupancy = {
            col: dict(q(f"SELECT {col}, COUNT(*) FROM {GTABLE} "
                        f"GROUP BY {col}"))
            for col in _TAG_VALUES}
        cols = [r[1] for r in q(f"PRAGMA table_info({GTABLE})")]
        return {
            "promoted_total": total,
            "by_ledger": dict(sorted(by_ledger.items())),
            "unique_candidate_ids": q(
                f"SELECT COUNT(DISTINCT candidate_id) FROM {GTABLE}"
            )[0][0],
            "unique_event_dates": q(
                f"SELECT COUNT(DISTINCT event_date) FROM {GTABLE}")[0][0],
            "primary_state_complete": q(
                f"SELECT COUNT(*) FROM {GTABLE} WHERE "
                + " AND ".join(f"{c} IS NOT NULL"
                               for c in _PRIMARY_STATE_COLUMNS))[0][0],
            "credit_available": q(
                f"SELECT COUNT(*) FROM {GTABLE} WHERE "
                "credit_availability = 'available'")[0][0],
            "credit_source_missing": q(
                f"SELECT COUNT(*) FROM {GTABLE} WHERE "
                "credit_availability = 'source_missing'")[0][0],
            "by_mapping": by_mapping,
            "tag_occupancy": {k: dict(sorted(v.items()))
                              for k, v in sorted(tag_occupancy.items())},
            "accepted_track_record": accepted_track_record_count(db_path),
            "gtable_columns": tuple(cols),
            "mapping_versions": dict(q(
                f"SELECT mapping_version, COUNT(*) FROM {GTABLE} "
                "GROUP BY mapping_version")),
            "freeze_versions": dict(q(
                f"SELECT freeze_version, COUNT(*) FROM {GTABLE} "
                "GROUP BY freeze_version")),
        }
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Live input builder (reuses the G4 pipeline verbatim)
# ---------------------------------------------------------------------------


def build_promotion_rows() -> list[dict[str, Any]]:
    """The 97 promotion rows from the frozen G4 pipeline.

    Reuses g4._load_live (which reconciles the universe fail-loud),
    freeze_dimension_statuses, and the frozen sign-tag rules. Aborts if
    the recomputed freeze differs from the committed G4 decisions.
    """
    rows, _recon = g4._load_live()
    statuses = g4.freeze_dimension_statuses(rows)
    expected = {"fed_policy_path": "primary_retained",
                "vix_level_percentile": "primary_retained",
                "spy_trend_ma200": "primary_retained",
                "curve_2s10s": "primary_retained",
                "credit_hy_oas": "secondary_subset_only"}
    got = {d: s["status"] for d, s in statuses.items()}
    if got != expected:
        raise ValueError(f"G4 freeze drift: statuses {got} != committed "
                         f"freeze {expected}; promotion aborted")
    out: list[dict[str, Any]] = []
    for r in rows:
        fam = r["family"]
        lens = TRANSMISSION_MAP[fam]
        if fam == "fomc":
            provenance = {
                "frame": "G1A FOMC frame inventory "
                         "(stats/G1A_FOMC_FRAME_INVENTORY.md)",
                "selection": "frame_member",
            }
        else:
            provenance = {
                "reservoir": "opec-production-policy-reservoir-2018-2025@v1"
                             " (stats/G1B_OPEC_DESIGNED_RESERVOIR.md)",
                "selection": "designed_recruitment "
                             "(g4-designed-recruitment-v1)",
            }
        credit = r["state"]["credit_hy_oas"]
        out.append({
            "candidate_id": r["candidate_id"],
            "denominator_ledger": r["lane"],
            "sampling_family": fam,
            "source_provenance": json.dumps(provenance, sort_keys=True),
            "event_date": r["event_date"],
            "cutoff": r["cutoff"],
            "mapping_version": MAPPING_VERSION,
            "primary_asset": lens.primary,
            "market_benchmark": lens.market,
            "sector_benchmark": lens.sector,
            "freeze_version": g4.FREEZE_VERSION,
            "state_fed_policy_path": r["state"]["fed_policy_path"],
            "state_vix_level_percentile":
                r["state"]["vix_level_percentile"],
            "state_spy_trend_ma200": r["state"]["spy_trend_ma200"],
            "state_curve_2s10s": r["state"]["curve_2s10s"],
            "state_credit_hy_oas": credit,
            "credit_availability": ("available" if credit is not None
                                    else "source_missing"),
            "tag_fed_policy_path": _classify(
                "fed_policy_path", r["state"]["fed_policy_path"]),
            "tag_spy_trend_ma200": _classify(
                "spy_trend_ma200", r["state"]["spy_trend_ma200"]),
            "tag_curve_2s10s": _classify(
                "curve_2s10s", r["state"]["curve_2s10s"]),
        })
    out.sort(key=lambda r: (r["event_date"], r["candidate_id"]))
    return out


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------


def run_proof(db_path: Path | str) -> dict[str, Any]:
    """Full promotion proof against `db_path` (a COPY for the temp proof,
    events.db itself for the live run - same tested path either way)."""
    pre_hashes = table_dump_hashes(db_path)
    pre_accepted = accepted_track_record_count(db_path)
    rows = build_promotion_rows()
    first = promote(db_path, rows)
    second = promote(db_path, rows)          # idempotence, same txn path
    post_hashes = table_dump_hashes(db_path)
    verify = verify_promotion(db_path)
    unchanged = pre_hashes == post_hashes
    return {
        "promotion_version": PROMOTION_VERSION,
        "input_rows": len(rows),
        "first_run": first,
        "second_run": second,
        "idempotent": second["inserted"] == 0,
        "pre_accepted": pre_accepted,
        "post_accepted": verify["accepted_track_record"],
        "pre_existing_tables_unchanged": unchanged,
        "changed_tables": sorted(k for k in pre_hashes
                                 if post_hashes.get(k) != pre_hashes[k]),
        "verify": verify,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="G5 promotion (temp proof first; live only after).")
    parser.add_argument("--temp-proof", metavar="COPY_PATH")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--verify", nargs="?", const=str(LIVE_DB),
                        metavar="DB_PATH")
    args = parser.parse_args(argv)
    if args.temp_proof:
        print(json.dumps(run_proof(args.temp_proof), indent=1,
                         sort_keys=True))
    elif args.live:
        print(json.dumps(run_proof(LIVE_DB), indent=1, sort_keys=True))
    elif args.verify:
        print(json.dumps(verify_promotion(args.verify), indent=1,
                         sort_keys=True))
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
