"""R0 zero-cost release-data sources (``r0-release-register-v1``).

Two reproducible primary layers feed the R0 register:

* **Release identity + scheduled timestamps** — the official BLS
  per-program schedule pages (``/schedule/news_release/cpi.htm`` and
  ``/schedule/news_release/empsit.htm``), read through PINNED Internet
  Archive (Wayback Machine) snapshots.  Live www.bls.gov refuses
  non-browser clients from this environment (HTTP 403, recorded by the
  source probe), and a pinned snapshot timestamp is byte-reproducible
  in a way a live page is not; the archived page is still the primary
  document.  One snapshot attests ~14 forward months, so one-or-two
  snapshots per calendar year give overlapping attestation of every
  release since the snapshot record begins (2008).
* **Point-in-time values** — the ALFRED (ArchivaL FRED) vintage layer
  of the official FRED API, using the existing authenticated free-key
  seam from ``scripts/g_state_acquisition.py``.  A vintage dated on the
  release day carries exactly the numbers the agency published that
  morning; the previous release's vintage carries the prior as
  originally published.  The key authenticates only; recorded URLs are
  redacted.

Parsers are pure and offline; fetch functions are explicitly
network-bound, zero-cost, and write only the gitignored local capture
directory given to them.  Nothing here reads or writes any application
storage.
"""

from __future__ import annotations

import gzip
import hashlib
import html as _html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from scripts import g_state_acquisition as gsa  # noqa: E402
from scripts import r0_release_register as r0r  # noqa: E402

SCHEDULE_PAGES = {
    "cpi": "https://www.bls.gov/schedule/news_release/cpi.htm",
    "employment": "https://www.bls.gov/schedule/news_release/empsit.htm",
}

WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
WAYBACK_SNAPSHOT = "https://web.archive.org/web/{timestamp}id_/{url}"

ALFRED_OBSERVATIONS = ("https://api.stlouisfed.org/fred/series/"
                       "observations")
ALFRED_VINTAGEDATES = ("https://api.stlouisfed.org/fred/series/"
                       "vintagedates")

_MONTHS = {name: i for i, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"), start=1)}
_MONTH_ABBREV = {name[:3].lower(): i for name, i in _MONTHS.items()}

_TABLE_RE = re.compile(r"<table[^>]*>.*?</table>", re.S)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_SCHED_DATE_RE = re.compile(r"^([A-Za-z]+)\.?\s+(\d{1,2}),\s+(\d{4})$")
_SCHED_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})\s+(AM|PM)$")
_REF_MONTH_RE = re.compile(r"^([A-Za-z]+)\s+(\d{4})$")
_VINTAGE_COL_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def _cell_text(cell_html: str) -> str:
    text = _html.unescape(_TAG_RE.sub(" ", cell_html))
    return " ".join(text.split())


def _parse_reference_month(text: str) -> Optional[str]:
    m = _REF_MONTH_RE.match(text)
    if not m or m.group(1) not in _MONTHS:
        return None
    return f"{int(m.group(2)):04d}-{_MONTHS[m.group(1)]:02d}"


def _parse_schedule_date(text: str) -> Optional[str]:
    m = _SCHED_DATE_RE.match(text)
    if not m:
        return None
    month = _MONTH_ABBREV.get(m.group(1)[:3].lower())
    if month is None:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(2))).isoformat()
    except ValueError:
        return None


def _parse_schedule_time(text: str) -> Optional[str]:
    m = _SCHED_TIME_RE.match(text)
    if not m:
        return None
    hour, minute, half = int(m.group(1)), m.group(2), m.group(3)
    if not 1 <= hour <= 12:
        return None
    if half == "AM":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12
    return f"{hour:02d}:{minute}"


def parse_schedule_html(text: str, *, release_name: str
                        ) -> tuple[list[dict[str, Any]],
                                   list[dict[str, Any]]]:
    """Parse one BLS schedule page into (entries, rejected_rows).

    A row whose reference month or release date cannot be parsed is
    REJECTED with its raw cells and a reason — never silently dropped —
    so the coverage probe can count every attempted row.  A row with an
    unparseable release time keeps its identity and carries
    ``release_time_local=None`` (the register fails it closed as
    ``timestamp_unresolved``).
    """
    marker = f"Schedule of Releases for the {release_name}"
    if marker not in text:
        raise ValueError(
            f"page does not carry the expected schedule marker: "
            f"{marker!r}")
    entries: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for table_html in _TABLE_RE.findall(text):
        rows = [[_cell_text(c) for c in _CELL_RE.findall(row_html)]
                for row_html in _ROW_RE.findall(table_html)]
        # older BLS markup nests the schedule table inside layout
        # tables and can glue the caption into a wider header row, so
        # the header signature is matched on the LAST three cells
        header_ok = any(
            len(r) >= 3 and r[-3].endswith("Reference Month") and
            r[-2].endswith("Release Date") and
            r[-1].endswith("Release Time") for r in rows)
        if not header_ok:
            continue
        for cells in rows:
            if len(cells) != 3 or cells[0].endswith("Reference Month"):
                continue
            reference_period = _parse_reference_month(cells[0])
            release_date = _parse_schedule_date(cells[1])
            problems = []
            if reference_period is None:
                problems.append(f"unparseable reference month: "
                                f"{cells[0]!r}")
            if release_date is None:
                problems.append(f"unparseable release date: {cells[1]!r}")
            if problems:
                rejected.append({"raw": cells,
                                 "reason": "; ".join(problems)})
                continue
            entries.append({
                "reference_period": reference_period,
                "release_date": release_date,
                "release_time_local": _parse_schedule_time(cells[2]),
                "raw": cells,
            })
    return entries, rejected


def merge_schedule_attestations(
        snapshots: Sequence[tuple[str, Sequence[Mapping[str, Any]]]]
        ) -> list[dict[str, Any]]:
    """Merge per-snapshot schedule entries into one attested register
    layer.  Distinct (date, time) claims for one reference period are a
    CONFLICT: every attestation is preserved and the merged entry keeps
    the conflict list, which the register contract fails closed as
    ``timestamp_unresolved``; nothing is silently resolved."""
    by_ref: dict[str, list[tuple[str, str, Optional[str]]]] = {}
    for snapshot_id, entries in sorted(snapshots, key=lambda s: s[0]):
        for entry in entries:
            by_ref.setdefault(entry["reference_period"], []).append(
                (str(snapshot_id), entry["release_date"],
                 entry["release_time_local"]))
    merged: list[dict[str, Any]] = []
    for reference_period in sorted(by_ref):
        attestations = by_ref[reference_period]
        claims = sorted({(d, t) for _, d, t in attestations})
        latest = max(attestations, key=lambda a: a[0])
        conflicts: list[dict[str, Any]] = []
        if len(claims) > 1:
            conflicts = [{"snapshot": sid, "release_date": d,
                          "release_time_local": t}
                         for sid, d, t in attestations]
        merged.append({
            "reference_period": reference_period,
            "release_date": latest[1],
            "release_time_local": latest[2],
            "attested_by": sorted({sid for sid, _, _ in attestations}),
            "schedule_conflicts": conflicts,
        })
    merged.sort(key=lambda e: (e["release_date"], e["reference_period"]))
    return merged


# ---------------------------------------------------------------------------
# ALFRED vintage layer
# ---------------------------------------------------------------------------


def parse_vintagedates(payload: Mapping[str, Any]) -> list[str]:
    dates = payload.get("vintage_dates")
    if not isinstance(dates, list) or not dates:
        raise ValueError("vintagedates payload carries no vintage_dates")
    out = []
    for value in dates:
        if not isinstance(value, str):
            raise ValueError(f"vintage date is not a string: {value!r}")
        date.fromisoformat(value)
        out.append(value)
    if out != sorted(out):
        raise ValueError("vintage dates are not ascending")
    return out


def parse_vintage_matrix(payload: Mapping[str, Any], *, series_id: str
                         ) -> dict[str, dict[str, float]]:
    """ALFRED ``output_type=2`` observations -> {reference month:
    {vintage ISO date: value}}.  The source's "." marker means missing
    and is skipped; any other unparseable value fails closed; a column
    for a different series fails closed."""
    prefix = f"{series_id}_"
    matrix: dict[str, dict[str, float]] = {}
    for observation in payload.get("observations", []):
        obs_date = observation.get("date", "")
        date.fromisoformat(obs_date)
        reference_period = obs_date[:7]
        for column, raw in observation.items():
            if column == "date":
                continue
            if not column.startswith(prefix):
                raise ValueError(
                    f"unexpected column {column!r} for series "
                    f"{series_id}")
            stamp = _VINTAGE_COL_RE.match(column[len(prefix):])
            if not stamp:
                raise ValueError(f"unparseable vintage column: "
                                 f"{column!r}")
            vintage = "-".join(stamp.groups())
            date.fromisoformat(vintage)
            if raw == ".":
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"malformed value {raw!r} in column {column!r} for "
                    f"observation {obs_date}") from exc
            matrix.setdefault(reference_period, {})[vintage] = value
    return matrix


def _previous_period(reference_period: str) -> str:
    year, month = int(reference_period[:4]), int(reference_period[5:7])
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


def extract_release_values(*, series: Mapping[str, str],
                           release_date: str, reference_period: str,
                           matrix: Mapping[str, Mapping[str, float]],
                           vintage_dates: Sequence[str]
                           ) -> dict[str, dict[str, Any]]:
    """Point-in-time join of one scheduled release against the vintage
    matrix.  ``actual`` and ``revised_prior`` may come only from the
    release-day vintage; ``prior`` is the previous reference month at
    its FIRST vintage ever (its own original publication), strictly
    before this release.  Every gap is an explicit missing cell."""
    def available(value: float, vintage: str) -> dict[str, Any]:
        return r0r.value_cell(
            value=value, unit=series["unit"],
            seasonal_adjustment=series["seasonal_adjustment"],
            measure_kind=series["measure_kind"], vintage_date=vintage)

    def missing(reason: str) -> dict[str, Any]:
        return r0r.value_cell(
            value=None, status="missing", unit=series["unit"],
            seasonal_adjustment=series["seasonal_adjustment"],
            measure_kind=series["measure_kind"], reason=reason)

    release_vintage_exists = release_date in set(vintage_dates)
    reference_cells = dict(matrix.get(reference_period, {}))
    previous_cells = dict(matrix.get(_previous_period(reference_period),
                                     {}))

    if not release_vintage_exists:
        actual = missing(f"no vintage exists on the release date "
                         f"{release_date}")
        revised_prior = missing(f"no vintage exists on the release date "
                                f"{release_date}")
    else:
        if release_date in reference_cells:
            actual = available(reference_cells[release_date],
                               release_date)
        else:
            actual = missing("reference month absent in the release-day "
                             "vintage")
        if release_date in previous_cells:
            revised_prior = available(previous_cells[release_date],
                                      release_date)
        else:
            revised_prior = missing("previous reference month absent in "
                                    "the release-day vintage")

    if not previous_cells:
        prior = missing("previous reference month never observed in the "
                        "captured vintages")
    else:
        first_vintage = min(previous_cells)
        if first_vintage >= release_date:
            prior = missing(
                f"first publication of the previous reference month "
                f"({first_vintage}) is not before the release date")
        else:
            prior = available(previous_cells[first_vintage],
                              first_vintage)

    return {"actual": actual, "prior": prior,
            "revised_prior": revised_prior}


# ---------------------------------------------------------------------------
# Capture layer (network-bound; zero-cost; writes only the given
# gitignored capture directory)
# ---------------------------------------------------------------------------

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,"
              "*/*;q=0.8",
}


def _get(url: str, timeout: int = 90,
         attempts: int = 4) -> bytes:  # pragma: no cover - network
    last: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = resp.read()
            # raw id_ archive captures replay the ORIGINAL stored
            # response, which may be gzip-encoded bytes
            if payload[:2] == b"\x1f\x8b":
                payload = gzip.decompress(payload)
            return payload
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            time.sleep(8.0 * (attempt + 1))
    raise RuntimeError(f"fetch failed after {attempts} attempts: "
                       f"{url.split('?')[0]}: {last}")


def probe_direct_bls(getter: Callable[..., bytes] = _get
                     ) -> dict[str, Any]:  # pragma: no cover - network
    """Evidence probe: is live www.bls.gov reachable from here?  The
    result is recorded in the capture metadata either way; the pinned
    Wayback snapshots stay the load-bearing identity source."""
    out: dict[str, Any] = {}
    for family, url in SCHEDULE_PAGES.items():
        try:
            raw = getter(url, timeout=20, attempts=1)
            out[family] = {"reachable": True, "bytes": len(raw)}
        except Exception as exc:  # noqa: BLE001 - bounded evidence capture
            out[family] = {"reachable": False,
                           "evidence": f"{type(exc).__name__}: {exc}"}
    return out


def wayback_monthly_index(page_url: str, start_year: int,
                          end_year: int,
                          getter: Callable[..., bytes] = _get
                          ) -> list[str]:  # pragma: no cover
    """Monthly-collapsed snapshot timestamps for the whole capture
    range in ONE index query.  Revisit records are included on purpose
    (the archive stores most captures as digest-identical revisits; a
    status filter would open multi-month attestation gaps).  The
    capture keeps one usable snapshot per half-year, falling back to
    alternates inside the half when a stamp fails to replay or lacks
    the schedule marker."""
    # NOTE: no "limit" parameter — the CDX API reads a NEGATIVE limit
    # as "last N results", so limit=-1 silently truncates the index to
    # the single most recent capture; monthly collapse already bounds
    # the result size
    qs = urllib.parse.urlencode({
        "url": page_url, "output": "json",
        "from": f"{start_year}0101", "to": f"{end_year}1231",
        "fl": "timestamp", "collapse": "timestamp:6"})
    rows = json.loads(getter(f"{WAYBACK_CDX}?{qs}").decode("utf-8"))
    return sorted({r[0] for r in rows[1:]})


def _half_key(stamp: str) -> str:
    return f"{stamp[:4]}H{1 if stamp[4:6] <= '06' else 2}"


def fetch_wayback_snapshot(page_url: str, timestamp: str,
                           getter: Callable[..., bytes] = _get
                           ) -> bytes:  # pragma: no cover - network
    return getter(WAYBACK_SNAPSHOT.format(timestamp=timestamp,
                                          url=page_url))


def _alfred_url(endpoint: str, api_key: str, **params: Any) -> str:
    query = {"api_key": api_key, "file_type": "json"}
    query.update(params)
    return f"{endpoint}?{urllib.parse.urlencode(query)}"


def fetch_vintagedates(series_id: str, api_key: str,
                       getter: Callable[..., bytes] = _get
                       ) -> dict[str, Any]:  # pragma: no cover - network
    url = _alfred_url(ALFRED_VINTAGEDATES, api_key,
                      series_id=series_id, limit=10000)
    return json.loads(getter(url).decode("utf-8"))


def fetch_vintage_matrix_year(series_id: str, year: int, api_key: str,
                              getter: Callable[..., bytes] = _get,
                              *, open_ended: bool = False
                              ) -> dict[str, Any]:  # pragma: no cover
    # the API rejects any future realtime_end except the documented
    # max-date sentinel, so the current-year chunk must be open-ended
    realtime_end = "9999-12-31" if open_ended else f"{year}-12-31"
    url = _alfred_url(
        ALFRED_OBSERVATIONS, api_key, series_id=series_id,
        observation_start=f"{year - 1}-11-01",
        observation_end=f"{year}-12-31",
        realtime_start=f"{year}-01-01", realtime_end=realtime_end,
        output_type=2)
    return json.loads(getter(url).decode("utf-8"))


def run_capture(dest: Path, *, start_year: int, end_year: int,
                env: Optional[Mapping[str, str]] = None,
                getter: Callable[..., bytes] = _get,
                retrieved_at: str,
                pause_seconds: float = 1.5
                ) -> dict[str, Any]:  # pragma: no cover - network
    """Capture the complete zero-cost source range into ``dest``.

    Writes raw source bytes plus one ``capture_meta.json`` carrying the
    pinned snapshot identities, redacted request URLs, sha256 of every
    file, the retrieval timestamp, and the direct-BLS evidence probe.
    Never touches anything outside ``dest``.
    """
    import os

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    api_key = gsa._fred_api_key(env if env is not None else os.environ,
                                ROOT / ".env")
    if not api_key:
        raise RuntimeError("FRED_API_KEY required for the ALFRED vintage "
                           "capture (free registered key); refusing to "
                           "fetch anonymously")

    files: dict[str, dict[str, Any]] = {}
    sources: dict[str, Any] = {"bls_direct_probe":
                               probe_direct_bls(getter)}

    def record(name: str, payload: bytes) -> None:
        (dest / name).write_bytes(payload)
        files[name] = {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload)}

    def record_existing(name: str) -> bool:
        """Resume support: reuse an already-captured file untouched."""
        path = dest / name
        if not path.exists():
            return False
        payload = path.read_bytes()
        files[name] = {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload)}
        return True

    snapshots: dict[str, list[str]] = {}
    for family, page_url in SCHEDULE_PAGES.items():
        marker = (f"Schedule of Releases for the "
                  f"{r0r.RELEASE_NAMES[family]}").encode("utf-8")
        index_name = f"cdx_{family}.json"
        if not record_existing(index_name):
            monthly = wayback_monthly_index(page_url, start_year,
                                            end_year, getter)
            record(index_name, json.dumps(
                {"monthly_stamps": monthly}, sort_keys=True
                ).encode("utf-8"))
        monthly = json.loads((dest / index_name).read_text(
            encoding="utf-8"))["monthly_stamps"]
        halves: dict[str, list[str]] = {}
        for stamp in monthly:
            halves.setdefault(_half_key(stamp), []).append(stamp)
        stamps: list[str] = []
        unusable: list[str] = []
        failed: list[str] = []
        consecutive_transport_failures = 0
        for half in sorted(halves):
            # newest stamp of the half first, alternates behind it
            candidates = sorted(halves[half], reverse=True)
            existing = next(
                (s for s in candidates if
                 (dest / f"schedule_{family}_{s}.htm").exists()), None)
            if existing is not None:
                record_existing(f"schedule_{family}_{existing}.htm")
                stamps.append(existing)
                continue
            for stamp in candidates:
                name = f"schedule_{family}_{stamp}.htm"
                try:
                    raw = getter(WAYBACK_SNAPSHOT.format(
                        timestamp=stamp, url=page_url), 60, 2)
                except (RuntimeError, urllib.error.URLError,
                        TimeoutError) as exc:
                    # a lost stamp is an attestation-density loss, not
                    # a data hole: record it visibly and try the next
                    # alternate — unless the host is clearly down, in
                    # which case stop fast and resume later
                    failed.append(f"{stamp}: {exc}")
                    consecutive_transport_failures += 1
                    if consecutive_transport_failures >= 4:
                        raise RuntimeError(
                            f"archive host unhealthy while fetching "
                            f"{family} snapshots ({len(failed)} "
                            f"failures); re-run --fetch to resume"
                            ) from exc
                    continue
                consecutive_transport_failures = 0
                time.sleep(pause_seconds)
                if marker not in raw:
                    unusable.append(stamp)
                    continue
                stamps.append(stamp)
                record(name, raw)
                break
        stamps.sort()
        snapshots[family] = stamps
        sources[f"schedule_{family}"] = {
            "page": page_url,
            "access": "Internet Archive Wayback Machine pinned "
                      "snapshots (raw id_ captures)",
            "snapshots": stamps,
            "unusable_snapshots": unusable,
            "failed_snapshot_fetches": failed,
        }

    for family in r0r.FAMILIES:
        for series in r0r.SERIES[family]:
            series_id = series["series_id"]
            vd_name = f"alfred_vintagedates_{series_id}.json"
            if not record_existing(vd_name):
                vintagedates = fetch_vintagedates(series_id, api_key,
                                                  getter)
                record(vd_name, json.dumps(vintagedates, sort_keys=True
                                           ).encode("utf-8"))
            vintagedates = json.loads(
                (dest / vd_name).read_text(encoding="utf-8"))
            first_year = int(parse_vintagedates(vintagedates)[0][:4])
            # matrix chunks start one year early so the first in-scope
            # year's original-prior vintages are present; a missing
            # chunk is a values hole, so failures here stay fail-loud
            for year in range(max(start_year - 1, first_year),
                              end_year + 1):
                name = f"alfred_matrix_{series_id}_{year}.json"
                if record_existing(name):
                    continue
                payload = fetch_vintage_matrix_year(
                    series_id, year, api_key, getter,
                    open_ended=(year == end_year))
                record(name, json.dumps(payload, sort_keys=True
                                        ).encode("utf-8"))
                time.sleep(pause_seconds)
            sources[f"alfred_{series_id}"] = {
                "endpoint": gsa._redact_api_key(_alfred_url(
                    ALFRED_OBSERVATIONS, "KEY", series_id=series_id,
                    output_type=2)),
                "access": "official FRED/ALFRED API (authenticated, "
                          "free registered key; key never recorded)",
            }

    meta = {
        "contract": r0r.R0_CONTRACT,
        "retrieved_at": retrieved_at,
        "start_year": start_year,
        "end_year": end_year,
        "schedule_snapshots": snapshots,
        "sources": sources,
        "files": dict(sorted(files.items())),
    }
    (dest / "capture_meta.json").write_text(
        json.dumps(meta, indent=1, sort_keys=True), encoding="utf-8")
    return meta
