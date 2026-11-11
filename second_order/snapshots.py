"""Stored market snapshots: read without network access, compare, list, and evaluate pinned data.

A snapshot belongs to one provider (its payload's `provider`: "fred", or "board-h15" for one built from a kept H.15
release package, see package_snapshots). Readiness reads the snapshot's own provider's series, and a source-bound
leg is evaluated only on snapshots of the provider its registry entry names; nothing is re-pointed across providers.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
import gzip
import hashlib
import json
import sqlite3
import zlib
from .data import DAILY_DATE_CONVENTION, Observation, Series, daily_observation_time, ny_date
from .evaluation import evaluate, history_readiness
from .market_calendar import observation_grid
from .registry import FRED, binding, resolve, source_bound
from .schema import Hypothesis, utc
from .scoring import Rules
from .store import digest, user_tables


# Adapters that classified from the requested start before the boundary was stored explicitly.
CLASSIFIED_FROM_REQUEST = {"fred-2"}


@dataclass(frozen=True)
class Snapshot:
    id: str
    payload: dict
    classified: dict[str, list[tuple[date, float | None, str]]]  # Series -> every stored date and status.

    @property
    def retrieved_at(self) -> datetime:
        return datetime.fromisoformat(self.payload["retrieved_at"])

    @property
    def provider(self) -> str:
        return self.payload["provider"]

    def grid(self, series_id: str) -> list[tuple[date, float | None]]:
        """The stored observation grid; classification was fixed at import, so it never drifts."""
        return observation_grid(self.classified[series_id])

    def classified_from(self, series_id: str) -> date:
        """Coverage boundary: every expected session from this date on is classified in the snapshot.

        This is not the first observation date; a weekend or holiday at the start has no session to
        classify. Snapshots without that guarantee fall back to their first classified date.
        """
        entry = self.payload.get("series", {}).get(series_id, {})
        if "classified_from" in entry:
            return date.fromisoformat(entry["classified_from"])
        if self.payload.get("adapter_version") in CLASSIFIED_FROM_REQUEST:
            return date.fromisoformat(self.payload["request"]["observation_start"])
        return self.classified[series_id][0][0]

    def coverage(self, series_id: str, day: date) -> dict:
        """Freshness policy B's test for one series (store.check_freshness): whether its recorded classification range,
        from the classification boundary to the last classified date, contains ``day``, and that date's status. Reads
        the stored classification only, never acquisition or retrieval time."""
        classified = self.classified.get(series_id) or []
        if not classified:
            return {"covered": False, "classified_from": None, "classified_through": None, "status": None}
        start, through = self.classified_from(series_id), classified[-1][0]
        covered = start <= day <= through
        status = next((status for when, _, status in classified if when == day), "not_listed") if covered else None
        return {"covered": covered, "classified_from": start, "classified_through": through, "status": status}


def has_market_tables(connection: sqlite3.Connection) -> bool:
    return "market_snapshots" in user_tables(connection)


def load_snapshot(connection: sqlite3.Connection, snapshot_id: str) -> Snapshot:
    row = connection.execute("SELECT payload FROM market_snapshots WHERE id=?", (snapshot_id,)).fetchone() \
        if has_market_tables(connection) else None
    if row is None:
        raise ValueError(f"No market snapshot {snapshot_id}")
    classified: dict[str, list] = {}
    for series_id, day, value, status in connection.execute(
            "SELECT series_id, date, value, status FROM market_observations WHERE snapshot_id=? ORDER BY series_id, date",
            (snapshot_id,)):
        classified.setdefault(series_id, []).append((date.fromisoformat(day), value, status))
    return Snapshot(snapshot_id, json.loads(row[0]), classified)


def _stated(provider: str, raw: bytes) -> dict[str, str]:
    """The source's text for each date in a series' copied source bytes: FRED's observations response, or a package
    import's canonical rows."""
    data = json.loads(raw)
    if provider == FRED:
        return {item["date"]: item["value"] for item in data["observations"]}
    return {str(day): text for day, text in data.items()}


def _number(text: str | None) -> float | None:
    """A stated value as the import read it: a decimal is that number; FRED's "." and the Board's ND are none."""
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def verify_snapshot(connection: sqlite3.Connection, snapshot_id: str) -> Snapshot:
    """A stored snapshot read back and checked against what its import recorded. Its ID must be the SHA-256 of its
    payload; each series' copied source bytes must match their recorded SHA-256; and its classified rows must match
    the recorded classification (each status count and the last classified date), the source's text for every date
    and the value that text states. Raises ValueError naming the first thing that does not verify. Reads only."""
    row = connection.execute("SELECT provider, retrieved_at, payload FROM market_snapshots WHERE id=?",
                             (snapshot_id,)).fetchone() if has_market_tables(connection) else None
    if row is None:
        raise ValueError(f"No market snapshot {snapshot_id}")
    label = f"Snapshot {snapshot_id[:12]}"
    payload = json.loads(row[2])
    if digest(payload) != snapshot_id or payload.get("provider") != row[0] or payload.get("retrieved_at") != row[1]:
        raise ValueError(f"{label} does not match its recorded identity")
    snapshot = load_snapshot(connection, snapshot_id)
    copies = dict(connection.execute("SELECT series_id, observations_gzip FROM market_series WHERE snapshot_id=?",
                                     (snapshot_id,)))
    if set(copies) != set(payload["series"]) or set(snapshot.classified) != set(payload["series"]):
        raise ValueError(f"{label} does not hold exactly the series it records")
    for series_id, entry in payload["series"].items():
        try:
            raw = gzip.decompress(copies[series_id])
            stated = _stated(snapshot.provider, raw)
        except (OSError, EOFError, zlib.error, ValueError, KeyError, TypeError, AttributeError):
            raise ValueError(f"{label}'s copy of {series_id} cannot be read") from None
        if hashlib.sha256(raw).hexdigest() != entry["observations_sha256"]:
            raise ValueError(f"{label}'s copy of {series_id} does not match its recorded SHA-256")
        rows = list(connection.execute("SELECT date, value, raw_value, status FROM market_observations WHERE "
                                       "snapshot_id=? AND series_id=? ORDER BY date", (snapshot_id, series_id)))
        if dict(sorted(Counter(status for *_, status in rows).items())) != entry["statuses"] or \
                rows[-1][0] != entry["classified_through"] or not set(stated) <= {day for day, *_ in rows}:
            raise ValueError(f"{label}'s classified rows of {series_id} do not match its recorded classification")
        for day, value, text, _ in rows:
            if text != stated.get(day) or value != _number(text):
                raise ValueError(f"{label}'s stored {series_id} row for {day} does not match its copied source")
    return snapshot


def list_snapshots(connection: sqlite3.Connection) -> list[dict]:
    if not has_market_tables(connection):
        return []
    listed = []
    for snapshot_id, payload in connection.execute("SELECT id, payload FROM market_snapshots ORDER BY retrieved_at, id"):
        data = json.loads(payload)
        row = {"snapshot_id": snapshot_id, "provider": data["provider"], "vintage_date": data["vintage_date"],
               "retrieved_at": data["retrieved_at"],
               "series": {sid: {key: entry[key] for key in ("first_date", "last_date", "rows", "statuses")}
                          for sid, entry in data["series"].items()}}
        if data["provider"] != FRED:  # Built locally from a kept package: say from which, and when it was built.
            row.update(retrieved_at_means=data["semantics"]["retrieved_at"], created_at=data["created_at"],
                       built_from={key: data["source"][key] for key in ("package_id", "package_sha256", "received_at")})
        listed.append(row)
    return listed


def pinned_series(observable_id: str, series_id: str, baseline: Snapshot, outcome: Snapshot,
                  published: date) -> Series:
    """History dated before publication comes only from the baseline; later dates from the outcome."""
    history = [(day, value) for day, value in baseline.grid(series_id) if day < published]
    later = [(day, value) for day, value in outcome.grid(series_id) if day >= published]
    points = tuple(Observation(daily_observation_time(day), value) for day, value in history + later)
    # The registry's binding names the source ("fred:DGS2", "board-h15:RIFLGFCY02_N.B"); times are the daily
    # convention's end-of-date placeholders, never observed times.
    return Series(observable_id, points, resolve(observable_id).source, "raw",
                  timestamp_basis=DAILY_DATE_CONVENTION, open_ended=True)


def evaluate_bound(connection: sqlite3.Connection, hypothesis_id: str, outcome_snapshot_id: str,
                   as_of: datetime, rules: Rules | None = None,
                   references: dict[str, tuple[float, ...]] | None = None) -> dict:
    """Evaluate a source-bound hypothesis on its freeze-time baseline and one named outcome snapshot."""
    row = connection.execute("SELECT payload FROM hypotheses WHERE id=?", (hypothesis_id,)).fetchone()
    bound_at_freeze = connection.execute("SELECT baseline_snapshot_id FROM freeze_bindings WHERE hypothesis_id=?",
                                         (hypothesis_id,)).fetchone() if has_market_tables(connection) else None
    if row is None or bound_at_freeze is None:
        raise ValueError("No hypothesis with a baseline snapshot bound at freeze")
    hypothesis = Hypothesis.model_validate_json(row[0])
    baseline, outcome = load_snapshot(connection, bound_at_freeze[0]), load_snapshot(connection, outcome_snapshot_id)
    as_of = utc(as_of)
    if outcome.retrieved_at > as_of:
        raise ValueError("The outcome snapshot was retrieved after the evaluation clock")
    if outcome.retrieved_at < baseline.retrieved_at:
        raise ValueError("The outcome snapshot predates the baseline")
    published = ny_date(hypothesis.event.published_at)
    for leg in hypothesis.legs:
        bound = binding(leg.observable_id)
        if bound is None:
            raise ValueError(f"Leg {leg.id} ({leg.observable_id}) is not bound to a market data provider")
        provider, series_id = bound
        for role, snapshot in (("baseline", baseline), ("outcome", outcome)):
            if snapshot.provider != provider:
                raise ValueError(f"The {role} snapshot comes from {snapshot.provider}, but leg {leg.id} is bound to "
                                 f"{provider} ({series_id}); a leg is never measured on another provider's data")
        if series_id not in outcome.classified or outcome.classified_from(series_id) > published:
            # Sessions between the publication date and the classification boundary would be invisible,
            # which would move the scoring anchor and shorten the horizon without any sign of it.
            covered = outcome.classified_from(series_id).isoformat() if series_id in outcome.classified else "nowhere"
            raise ValueError(f"The outcome snapshot covers {series_id} from {covered}; it must start on or "
                             f"before the publication date {published.isoformat()}")
    series = {leg.observable_id: pinned_series(leg.observable_id, binding(leg.observable_id)[1], baseline, outcome,
                                               published)
              for leg in hypothesis.legs}
    payload = evaluate(hypothesis, series, as_of, rules, references)
    payload["snapshots"] = {"baseline": baseline.id, "outcome": outcome.id,
                            "history_from": "baseline, dates before the publication date",
                            "scored_from": "outcome, dates from the publication date"}
    return payload


def snapshot_readiness(snapshot: Snapshot, rules: Rules | None = None, before: date | None = None) -> dict:
    """History the snapshot offers an event anchor dated before `before` (default: after its last date).

    A stored snapshot is not necessarily enough to evaluate. This runs the scorer's own reference-window
    and placebo-control selection on the stored grid, under the active rules, at the same event anchor an
    evaluation would use: the last stored observation dated before the publication date.
    """
    rules = rules or Rules()
    report = {"snapshot_id": snapshot.id, "rules_version": rules.version, "rules_hash": rules.hash,
              "event_anchor": f"last stored observation dated before {before.isoformat()}" if before
              else "last stored observation", "series": {}}
    for observable_id, series_id in sorted(source_bound(snapshot.provider).items()):
        if series_id not in snapshot.classified:
            continue
        grid = [(day, value) for day, value in snapshot.grid(series_id) if before is None or day < before]
        entry: dict = {"observable_id": observable_id, "history_sessions": len(grid)}
        if grid:
            history = Series(observable_id, tuple(Observation(daily_observation_time(day), value) for day, value in grid),
                             resolve(observable_id).source, "raw", timestamp_basis=DAILY_DATE_CONVENTION)
            entry["event_anchor"] = grid[-1][0].isoformat()
            entry["horizons"] = {str(h): history_readiness(history, len(grid) - 1, h, rules) for h in (1, 5, 20)}
        else:
            entry["horizons"] = {str(h): {"horizon": h, "scorable": False, "reason": "No stored history",
                                          "reference_windows": 0, "required_reference_windows": rules.min_windows}
                                 for h in (1, 5, 20)}
        entry["scorable_horizons"] = [int(h) for h, item in entry["horizons"].items() if item["scorable"]]
        report["series"][series_id] = entry
    return report


def snapshot_revisions(old: Snapshot, new: Snapshot) -> list[dict]:
    """Dates whose stored value or status differ between two snapshots; nothing is overwritten."""
    if old.provider != new.provider:
        raise ValueError(f"Snapshots from different providers ({old.provider}, {new.provider}) are not revisions of "
                         "each other; compare snapshots of one provider")
    changes = []
    for series_id in sorted(set(old.classified) & set(new.classified)):
        before = {day: (value, status) for day, value, status in old.classified[series_id]}
        after = {day: (value, status) for day, value, status in new.classified[series_id]}
        for day in sorted(before):  # Dates only in the newer snapshot are extensions, not revisions.
            if day not in after or before[day] != after[day]:
                changes.append({"series": series_id, "date": day.isoformat(),
                                "before": dict(zip(("value", "status"), before[day])),
                                "after": dict(zip(("value", "status"), after[day])) if day in after else None})
    return changes
