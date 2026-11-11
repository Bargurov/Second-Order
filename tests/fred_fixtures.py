"""Synthetic FRED-format responses for offline tests. No network; the key below is fake."""
from datetime import date, timedelta
import json
import math
import httpx
from second_order.market_calendar import expected_sessions

FAKE_KEY = "abcdefghijklmnopqrstuvwxyz012345"
FIRST = date(2023, 1, 2)
SESSIONS = expected_sessions(FIRST, date(2026, 12, 31))


def dataset(through: date, overrides: dict | None = None, offset: float = 0.0,
            first: date = FIRST) -> list[tuple[date, str]]:
    """Weekday rows like FRED's: a value on bond-market sessions, '.' on weekday holidays."""
    rows, day = [], first
    while day <= through:
        if day.weekday() < 5:
            raw = f"{4 + offset + .25 * math.sin(day.toordinal() / 9):.2f}" if day in SESSIONS else "."
            rows.append((day, (overrides or {}).get(day, raw)))
        day += timedelta(days=1)
    return rows


def datasets(through: date, overrides: dict | None = None, first: date = FIRST) -> dict[str, list[tuple[date, str]]]:
    overrides = overrides or {}
    return {"DGS2": dataset(through, overrides.get("DGS2"), -.3, first),
            "DGS10": dataset(through, overrides.get("DGS10"), 0.0, first)}


class FakeFred:
    """MockTransport handler serving vintage-pinned responses and recording requests without the key."""

    def __init__(self, data, vintage: date, metadata=None, status=None, raise_for=None, echo_key=False,
                 patch_observations=None):
        self.data, self.vintage = data, vintage.isoformat()
        self.metadata, self.status = metadata or {}, status or {}
        self.raise_for, self.echo_key = raise_for, echo_key
        self.patch_observations = patch_observations or {}
        self.calls, self.keys = [], []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.keys.append(params.pop("api_key", None))
        endpoint = "observations" if request.url.path.endswith("/observations") else "series"
        series = params["series_id"]
        self.calls.append((endpoint, params))
        if self.raise_for == series:
            raise httpx.ConnectError(f"connection failed for {request.url}", request=request)
        pinned = {"realtime_start": self.vintage, "realtime_end": self.vintage}
        if endpoint == "series":
            entry = {"id": series, "title": f"Market Yield ({series})", "units": "Percent", "frequency_short": "D",
                     "seasonal_adjustment_short": "NSA", "last_updated": "2025-06-02 15:16:00-05", **pinned,
                     "notes": "For further information, see the H.15 Statistical Release notes."}
            payload = {**pinned, "seriess": [entry | self.metadata.get(series, {})]}
        else:
            start = date.fromisoformat(params["observation_start"])  # FRED returns rows from this date on.
            payload = {**pinned, "observation_start": params["observation_start"],
                       "observations": [{**pinned, "date": day.isoformat(), "value": raw}
                                        for day, raw in self.data[series] if day >= start]}
            if series in self.patch_observations:
                payload = self.patch_observations[series](payload)
        if self.echo_key:
            payload["debug"] = FAKE_KEY
        return httpx.Response(self.status.get((endpoint, series), 200), text=json.dumps(payload))

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))
