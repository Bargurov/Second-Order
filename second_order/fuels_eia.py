"""The fuels importer (fuels-eia-0.1): the only fuels module that touches the network, run only by `fuels refresh`.

It reads the five daily spot series of the committed source record from EIA's open data API (v2): for each series,
GET https://api.eia.gov/v2/<route>/data/ with its series facet, frequency=daily, data[0]=value, the window from
observation_start to retrieved_on and period ascending, paging by offset until the reply's stated total is reached.

A series is kept only when it came back whole and is the series the record names:
- every row names the series, and EIA's description and units for it exactly as the record states them;
- the reply's frequency is daily, every period is a day inside the window, and the periods strictly increase across
  all pages (pages that overlap refuse the series);
- every value is a plain decimal (kept as the exact text EIA sent) or null (no value that day);
- the rows add up to the reply's stated total: a warning (EIA warns when it caps a reply), a total that changes
  between pages, a page that ends early or more rows than the total refuses the series, never a partial history.
A refused series is recorded with its reason and no observations; the others are still kept.

The API key is the caller's. It is sent as the api_key parameter EIA requires and never stored, logged, printed or
put in an error message. EIA echoes it in request.params of every reply: that field is dropped before a reply is
hashed or read, and a reply that carries the key anywhere else aborts the refresh with nothing written. A failed
request (a network error, or HTTP 401, 403, 429 or 5xx) aborts the refresh and reports only its HTTP status and EIA's
error code; any other HTTP error refuses that series alone.

Dates are kept apart: the observation date (the trading day a price describes); EIA's publication date, which the API
does not give, so it is stored as unknown and shown as missing, never inferred from the observation date or the
retrieval; and retrieved_at, our clock after the last reply. A history is what EIA's file held when it was retrieved,
not a record of what was known on the days it covers. The returned report carries identities, dates, states and
counts, and no price values.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote

import httpx

from . import fuels_snapshots, fuels_sources, store
from .data import ny_date
from .fred import ImportRefused  # the shared refusal the CLI prints as "Failed: ..."; nothing of FRED is used
from .schema import utc

ADAPTER_VERSION = "fuels-eia-0.1"
EIA_API = "https://api.eia.gov/v2"
HISTORY_DAYS = 400
PAGE_ROWS = 5000  # EIA's documented maximum per JSON reply
ABORT_STATUSES = {401, 403, 429}  # the key or the rate limit, not the series
_PLAIN = re.compile(r"-?[0-9]+(\.[0-9]+)?")  # ASCII digits only
_CODE = re.compile(r"[A-Z][A-Z0-9_]{1,59}")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_VERSION = re.compile(r"[A-Za-z0-9._-]{1,40}")
_MAX_QUOTED = 120


class SeriesRefused(Exception):
    """One series is not kept: its message names the series and the rule, never a value or the key."""


def _quoted(text: object) -> str:
    """Text EIA sent, shortened, for a refusal (the key was checked absent from the reply before any is quoted)."""
    return repr(str(text)[:_MAX_QUOTED])


def _secrets(api_key: str) -> tuple[str, ...]:
    return tuple({api_key, quote(api_key, safe="")})


def _error_code(body: bytes, api_key: str) -> str | None:
    """EIA's error code ({"error": {"code": "API_KEY_INVALID", ...}}) when it is a plain code without the key."""
    try:
        payload = json.loads(body)
    except ValueError:
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    if isinstance(code, str) and _CODE.fullmatch(code) and not any(secret in code for secret in _secrets(api_key)):
        return code
    return None


def _without_key(payload: object, api_key: str, series_id: str) -> dict:
    """The reply with request.params.api_key dropped; a reply that holds the key anywhere else aborts the refresh."""
    if not isinstance(payload, dict):
        raise SeriesRefused(f"EIA's reply for {series_id} is not an object")
    request = payload.get("request")
    if isinstance(request, dict) and isinstance(request.get("params"), dict) and "api_key" in request["params"]:
        params = {name: value for name, value in request["params"].items() if name != "api_key"}
        payload = {**payload, "request": {**request, "params": params}}
    text = json.dumps(payload, ensure_ascii=False)
    if any(secret in text for secret in _secrets(api_key)):
        raise ImportRefused(f"EIA's reply for {series_id} carried the credential outside request.params; "
                            "nothing was stored")
    return payload


def fetch(client: httpx.Client, route: str, params: dict, api_key: str, series_id: str) -> dict:
    """One page of one series, its key already dropped. The URL (which carries the key) never enters a message."""
    try:
        response = client.get(f"{EIA_API}/{route}/data/", params={**params, "api_key": api_key})
    except httpx.HTTPError as exc:
        raise ImportRefused(f"EIA request for {series_id} failed ({type(exc).__name__})") from None
    if response.status_code != 200:
        code = _error_code(response.content, api_key)
        message = f"EIA request for {series_id} returned HTTP {response.status_code}" + (f" ({code})" if code else "")
        if response.status_code in ABORT_STATUSES or response.status_code >= 500:
            raise ImportRefused(message)
        raise SeriesRefused(message)
    try:  # Numbers stay as the exact text EIA sent: a price is never passed through a binary float.
        payload = json.loads(response.content, parse_float=str, parse_int=str)
    except (ValueError, UnicodeDecodeError):
        if any(secret.encode() in response.content for secret in _secrets(api_key)):
            raise ImportRefused(f"EIA's reply for {series_id} carried the credential; nothing was stored") from None
        raise SeriesRefused(f"EIA's reply for {series_id} is not JSON") from None
    return _without_key(payload, api_key, series_id)


def _count(value: object) -> int | None:
    return int(value) if isinstance(value, str) and value.isdigit() and value.isascii() else None


def _warned(payload: dict) -> bool:
    places = (payload, payload.get("response") if isinstance(payload.get("response"), dict) else {})
    return any(key in place for place in places for key in ("warning", "warnings"))


def _rows(get, record: dict, start: date, end: date) -> tuple[list[dict], dict]:
    """Every row of one series in the window, and what the replies said of it; SeriesRefused unless it came whole."""
    series_id = record["series_id"]
    base = {"frequency": "daily", "data[0]": "value", "facets[series][]": series_id, "start": start.isoformat(),
            "end": end.isoformat(), "sort[0][column]": "period", "sort[0][direction]": "asc",
            "length": str(PAGE_ROWS)}
    rows, hashes, total, versions = [], [], None, set()
    days = (end - start).days + 1  # a daily series holds at most one row per day of the window
    while True:
        payload = get(record["eia_route"], {**base, "offset": str(len(rows))}, series_id)
        hashes.append(hashlib.sha256(store.canonical(payload).encode("utf-8")).hexdigest())
        response = payload.get("response")
        if not isinstance(response, dict):
            raise SeriesRefused(f"EIA's reply for {series_id} has no response")
        if _warned(payload):
            raise SeriesRefused(f"EIA's reply for {series_id} carries a warning, so it may not be whole")
        if response.get("frequency") != "daily":
            raise SeriesRefused(f"EIA's reply for {series_id} is not daily: {_quoted(response.get('frequency'))}")
        stated = _count(response.get("total"))
        if stated is None:
            raise SeriesRefused(f"EIA's reply for {series_id} states no row count")
        if total is not None and stated != total:
            raise SeriesRefused(f"EIA's row count for {series_id} changed between pages")
        total = stated
        if total > days:
            raise SeriesRefused(f"EIA states {total} rows for {series_id}, more than the requested window can hold "
                                f"({days} days)")
        data = response.get("data")
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise SeriesRefused(f"EIA's reply for {series_id} has no list of rows")
        if data and rows and str(data[0].get("period")) <= str(rows[-1].get("period")):
            raise SeriesRefused(f"EIA's pages for {series_id} overlap or are out of order")
        version = payload.get("apiVersion")
        versions.add(version if isinstance(version, str) and _VERSION.fullmatch(version) else None)
        rows.extend(data)
        if len(rows) > total:
            raise SeriesRefused(f"EIA sent more rows for {series_id} than its stated total")
        if len(rows) == total:
            break
        if not data:
            raise SeriesRefused(f"EIA's replies for {series_id} ended at {len(rows)} of {total} rows")
    if total == 0:
        raise SeriesRefused(f"EIA returned no observations for {series_id}")
    version = versions.pop() if len(versions) == 1 else None
    return rows, {"pages": len(hashes), "total": total, "api_version": version, "responses_sha256": hashes}


def _observations(rows: list[dict], record: dict, start: date, end: date) -> list[list]:
    series_id, out, previous = record["series_id"], [], None
    for row in rows:
        if row.get("series") != series_id:
            raise SeriesRefused(f"EIA's reply for {series_id} holds a row of another series: {_quoted(row.get('series'))}")
        if row.get("series-description") != record["eia_description"]:
            raise SeriesRefused(f"EIA describes {series_id} as {_quoted(row.get('series-description'))}; the record "
                                f"says {_quoted(record['eia_description'])}")
        if row.get("units") != record["eia_units"]:
            raise SeriesRefused(f"{series_id} units changed: EIA says {_quoted(row.get('units'))}, the record says "
                                f"{_quoted(record['eia_units'])}")
        period = row.get("period")
        try:
            day = date.fromisoformat(period) if isinstance(period, str) and _DAY.fullmatch(period) else None
        except ValueError:
            day = None
        if day is None:
            raise SeriesRefused(f"EIA's reply for {series_id} has a period that is not a day")
        if not start <= day <= end:
            raise SeriesRefused(f"EIA's reply for {series_id} has a day outside the requested window")
        if previous is not None and day <= previous:
            raise SeriesRefused(f"EIA's days for {series_id} do not strictly increase (a repeated or overlapping page)")
        raw = row.get("value")
        if raw is not None and not (isinstance(raw, str) and _PLAIN.fullmatch(raw)):
            raise SeriesRefused(f"{series_id} has a value on {day.isoformat()} that is not a plain decimal")
        out.append([day.isoformat(), raw])
        previous = day
    return out


def _entry(state: str, problem: str | None, record: dict, metadata: dict | None, observations: list,
           hashes: list) -> dict:
    return {"state": state, "problem": problem, "terms": record, "metadata": metadata, "release": None,
            "release_dates": [], "observations": observations, "responses_sha256": hashes}


def refresh(snapshots: Path, content: Path, api_key: str, observation_start: date | None = None,
            client: httpx.Client | None = None, clock=lambda: datetime.now(timezone.utc)) -> dict:
    """Fetch the five series up to today's New York date and append one snapshot. Returns no values."""
    if not api_key:
        raise ImportRefused("EIA_API_KEY is not set; only the refresh command reads it")
    sources, sources_sha = fuels_sources.load_sources(content)
    retrieved_on = ny_date(utc(clock()))
    observation_start = observation_start or retrieved_on - timedelta(days=HISTORY_DAYS)
    if observation_start >= retrieved_on:
        raise ImportRefused("The observation start must precede the retrieval date")
    entries, requests = {}, 0
    own_client = client is None
    client = client or httpx.Client(timeout=30.0)

    def get(route: str, params: dict, series_id: str) -> dict:
        nonlocal requests
        requests += 1
        return fetch(client, route, params, api_key, series_id)

    try:
        for record in sources["series"]:
            series_id = record["series_id"]
            metadata, hashes = None, []
            try:
                rows, said = _rows(get, record, observation_start, retrieved_on)
                hashes = said.pop("responses_sha256")
                metadata = {"route": record["eia_route"], "series": series_id,
                            "description": record["eia_description"], "units": record["eia_units"],
                            "frequency": "daily", **said}
                entries[series_id] = _entry("stored", None, record, metadata,
                                            _observations(rows, record, observation_start, retrieved_on), hashes)
            except SeriesRefused as exc:
                entries[series_id] = _entry("refused", str(exc), record, metadata, [], hashes)
    finally:
        if own_client:
            client.close()
    retrieved_at = utc(clock()).isoformat()
    payload = {"snapshot_version": fuels_snapshots.SNAPSHOT_VERSION, "adapter_version": ADAPTER_VERSION,
               "provider": "eia", "semantics": fuels_snapshots.SEMANTICS, "retrieved_on": retrieved_on.isoformat(),
               "observation_start": observation_start.isoformat(), "observation_end": retrieved_on.isoformat(),
               "retrieved_at": retrieved_at, "sources_sha256": sources_sha,
               "request": {"endpoint": EIA_API, "frequency": "daily", "data": ["value"], "sort": "period ascending",
                           "page_rows": PAGE_ROWS},
               "series": entries}
    snapshot_id, created = fuels_snapshots.write(snapshots, payload)
    summary = {}
    for series_id, entry in entries.items():
        obs = entry["observations"]
        summary[series_id] = {"state": entry["state"], "problem": entry["problem"], "rows": len(obs),
                              "first_date": obs[0][0] if obs else None, "last_date": obs[-1][0] if obs else None,
                              "publication_date": None}
    return {"snapshot_id": snapshot_id, "created": created, "retrieved_on": retrieved_on.isoformat(),
            "retrieved_at": retrieved_at, "requests": requests, "series": summary}
