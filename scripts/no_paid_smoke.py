#!/usr/bin/env python3
"""No-paid local demo smoke check.

Runs the demo-critical zero-cost endpoints that should work without
LLM, yfinance, market-data provider, or paid backfill calls.  Default
mode uses FastAPI's in-process TestClient and guards known paid/provider
seams with raisers so regressions fail loudly.  ``--base-url`` can probe
a running local server, but in-process mode is the strongest no-paid
guard because it can monkey-patch the Python seams.

Usage:
    python scripts/no_paid_smoke.py
    python scripts/no_paid_smoke.py --json
    python scripts/no_paid_smoke.py --base-url http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


BodyInvariant = Callable[[Any], None]


def _assert_auto_backfill_status_no_paid(body: Any) -> None:
    """Pin no-paid invariants on the auto-backfill-status response.

    The diagnostics surface must report a not-wired skeleton in the
    no-paid demo: ``scheduler.scheduler_started`` must be false (no
    background scheduler running) and ``ledger.used`` must be zero (no
    paid call has been reserved).  A regression on either field means
    paid execution or background scheduling slipped in — fail closed.
    """
    if not isinstance(body, dict):
        raise AssertionError(
            f"auto-backfill-status response must be a JSON object, "
            f"got {type(body).__name__}"
        )
    scheduler = body.get("scheduler") or {}
    started = scheduler.get("scheduler_started")
    if started is not False:
        raise AssertionError(
            f"scheduler.scheduler_started must be false in no-paid mode, "
            f"got {started!r}"
        )
    ledger = body.get("ledger") or {}
    used = ledger.get("used")
    if used != 0:
        raise AssertionError(
            f"ledger.used must be 0 in no-paid mode, got {used!r}"
        )


@dataclass(frozen=True)
class SmokeEndpoint:
    name: str
    path: str
    expected_statuses: tuple[int, ...] = (200,)
    method: str = "GET"
    body_invariants: tuple[BodyInvariant, ...] = field(default_factory=tuple)


@dataclass
class SmokeResult:
    name: str
    path: str
    ok: bool
    status_code: int | None
    elapsed_ms: int
    error: str | None = None


ENDPOINTS: tuple[SmokeEndpoint, ...] = (
    SmokeEndpoint("health", "/health"),
    SmokeEndpoint("config health", "/diagnostics/config-health"),
    SmokeEndpoint(
        "auto backfill status",
        "/diagnostics/auto-backfill-status",
        body_invariants=(_assert_auto_backfill_status_no_paid,),
    ),
    SmokeEndpoint("data quality", "/diagnostics/data-quality"),
    SmokeEndpoint("archive stats", "/diagnostics/archive-stats"),
    SmokeEndpoint("validation stats", "/diagnostics/validation-status-stats"),
    SmokeEndpoint("reaction stats", "/diagnostics/reaction-profile-stats"),
    SmokeEndpoint("track record", "/diagnostics/track-record"),
    SmokeEndpoint(
        "major skipped",
        "/diagnostics/major-skipped-headlines?limit=5",
    ),
    SmokeEndpoint(
        "pending archive",
        "/events?limit=3&validation_status_v2=pending",
    ),
    # Some local archives do not retain row id 1.  A JSON 404 still
    # proves the detail route is mounted and guarded; seeded tests pin
    # the 200 path.
    SmokeEndpoint("event detail", "/events/1", (200, 404)),
    SmokeEndpoint("candidate queue", "/registry/candidate-queue?limit=5"),
    SmokeEndpoint("backfill preview", "/movers/backfill-preview?limit=5"),
    SmokeEndpoint(
        "auto backfill dry-run",
        "/diagnostics/auto-backfill-dry-run",
        method="POST",
    ),
)


_BANNED_PATH_MARKERS: tuple[str, ...] = (
    "/analyze",
    "/analyze/stream",
    "/movers/backfill-recent",
    "/movers/backfill-candidate",
)


_DANGEROUS_SEAMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "api",
        (
            "analyze_event",
            "market_check",
            "followup_check",
            "macro_snapshot",
            "refresh_market_for_saved_event",
        ),
    ),
    (
        "analyze_event",
        (
            "analyze_event",
            "_call_llm_provider",
            "_call_anthropic",
            "_call_openai",
        ),
    ),
    (
        "market_check",
        (
            "_fetch",
            "_fetch_since",
            "market_check",
            "followup_check",
            "macro_snapshot",
            "compute_rates_context",
            "compute_stress_regime",
            "ticker_chart",
            "ticker_info",
        ),
    ),
    ("market_data", ("get_provider", "reload_provider_from_env")),
    ("price_cache", ("fetch_daily_cached",)),
    (
        "db",
        (
            "save_event",
            "save_movers_cache",
            "clear_movers_cache",
            "delete_event",
            "update_review",
            "append_revisit_snapshot",
        ),
    ),
    ("headline_registry", ("advance_state", "stamp_expired_if_observed")),
    (
        "routes.movers",
        (
            "_fresh_analysis_market_event",
            "_refresh_existing_market_event",
            "movers_backfill_recent",
            "movers_backfill_candidate",
        ),
    ),
)


def _empty_mover_slices(*_args, **_kwargs) -> dict[str, list[dict]]:
    return {"today": [], "market": [], "weekly": [], "persistent": []}


_READONLY_STUB_SEAMS: tuple[tuple[str, str, Any], ...] = (
    (
        "routes.movers",
        "load_ui_slices_for_event_context",
        _empty_mover_slices,
    ),
)


def _guard_raiser(label: str):
    def _raise(*_args, **_kwargs):
        raise RuntimeError(f"no-paid smoke attempted forbidden seam: {label}")

    return _raise


@contextlib.contextmanager
def guard_no_paid_provider_calls():
    """Temporarily replace known paid/provider/write seams with raisers.

    A small route-side cache reader used by event detail is stubbed to
    empty mover slices so the smoke remains a DB-read preflight instead
    of bootstrapping persisted mover caches.
    """
    patched: list[tuple[Any, str, Any]] = []
    for module_name, attr_name, replacement in _READONLY_STUB_SEAMS:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        if not hasattr(module, attr_name):
            continue
        original = getattr(module, attr_name)
        setattr(module, attr_name, replacement)
        patched.append((module, attr_name, original))
    for module_name, attr_names in _DANGEROUS_SEAMS:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        for attr_name in attr_names:
            if not hasattr(module, attr_name):
                continue
            original = getattr(module, attr_name)
            setattr(module, attr_name, _guard_raiser(f"{module_name}.{attr_name}"))
            patched.append((module, attr_name, original))
    try:
        yield
    finally:
        for module, attr_name, original in reversed(patched):
            setattr(module, attr_name, original)


@contextlib.contextmanager
def _quiet_request_loggers():
    names = ("httpx", "second_order.movers_cache")
    original: list[tuple[logging.Logger, int, bool]] = []
    for name in names:
        logger = logging.getLogger(name)
        original.append((logger, logger.level, logger.propagate))
        logger.setLevel(logging.WARNING)
        logger.propagate = False
    try:
        yield
    finally:
        for logger, level, propagate in original:
            logger.setLevel(level)
            logger.propagate = propagate


def _assert_endpoint_inventory_is_zero_cost() -> None:
    for endpoint in ENDPOINTS:
        if endpoint.method.upper() not in {"GET", "POST"}:
            raise AssertionError(
                f"no-paid smoke inventory has unsupported method: "
                f"{endpoint.method} {endpoint.path}"
            )
        for marker in _BANNED_PATH_MARKERS:
            if endpoint.path.startswith(marker):
                raise AssertionError(
                    f"no-paid smoke inventory includes paid path: {endpoint.path}"
                )


def _make_test_client():
    from fastapi.testclient import TestClient
    import api

    return TestClient(api.app)


class _HttpResponse:
    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self._body = body

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


class _LocalHttpClient:
    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str) -> _HttpResponse:
        url = self.base_url + path
        request = urllib.request.Request(url, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return _HttpResponse(response.status, response.read())
        except urllib.error.HTTPError as exc:
            return _HttpResponse(exc.code, exc.read())

    def get(self, path: str) -> _HttpResponse:
        return self.request("GET", path)

    def post(self, path: str) -> _HttpResponse:
        return self.request("POST", path)


def _response_is_json_parseable(response: Any) -> tuple[bool, str | None]:
    try:
        response.json()
    except Exception as exc:
        return False, f"response was not JSON parseable: {type(exc).__name__}: {exc}"
    return True, None


def _check_body_invariants(
    response: Any,
    invariants: tuple[BodyInvariant, ...],
) -> tuple[bool, str | None]:
    """Run the per-endpoint body invariants on a successful response.

    Each invariant takes the parsed JSON body and raises on failure.
    Returns ``(ok, error)``: ``ok`` is True when every invariant
    passes; ``error`` carries the raised message verbatim so the
    smoke output explains why the check failed.
    """
    if not invariants:
        return True, None
    try:
        body = response.json()
    except Exception as exc:
        return False, (
            f"could not parse response for invariants: "
            f"{type(exc).__name__}: {exc}"
        )
    for invariant in invariants:
        try:
            invariant(body)
        except AssertionError as exc:
            return False, f"body invariant failed: {exc}"
    return True, None


def _request(client: Any, endpoint: SmokeEndpoint) -> Any:
    method = endpoint.method.upper()
    if hasattr(client, "request"):
        return client.request(method, endpoint.path)
    attr = method.lower()
    if not hasattr(client, attr):
        raise AttributeError(f"client does not support {method}")
    return getattr(client, attr)(endpoint.path)


def run_smoke(
    *,
    client: Any | None = None,
    base_url: str | None = None,
    timeout: float = 5.0,
    guard_provider_seams: bool = True,
) -> list[SmokeResult]:
    """Run the smoke checks and return per-endpoint results.

    The checks are zero-cost HTTP probes.  Success means the expected
    HTTP status was returned and the response body parsed as JSON.
    """
    _assert_endpoint_inventory_is_zero_cost()
    if client is not None and base_url:
        raise ValueError("Pass either client or base_url, not both.")

    if client is None:
        client = _LocalHttpClient(base_url, timeout) if base_url else _make_test_client()

    guard = guard_no_paid_provider_calls() if guard_provider_seams and not base_url else contextlib.nullcontext()
    results: list[SmokeResult] = []
    with guard, _quiet_request_loggers():
        for endpoint in ENDPOINTS:
            start = time.perf_counter()
            status_code: int | None = None
            ok = False
            error: str | None = None
            try:
                response = _request(client, endpoint)
                status_code = int(response.status_code)
                if status_code not in endpoint.expected_statuses:
                    error = (
                        f"expected HTTP {endpoint.expected_statuses}, got "
                        f"HTTP {status_code}"
                    )
                else:
                    ok, error = _response_is_json_parseable(response)
                    if ok and endpoint.body_invariants:
                        ok, error = _check_body_invariants(
                            response, endpoint.body_invariants,
                        )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            results.append(
                SmokeResult(
                    name=endpoint.name,
                    path=endpoint.path,
                    ok=bool(ok and error is None),
                    status_code=status_code,
                    elapsed_ms=elapsed_ms,
                    error=error,
                )
            )
    return results


def summarize(results: list[SmokeResult]) -> dict[str, Any]:
    passed = sum(1 for r in results if r.ok)
    total = len(results)
    return {
        "ok": passed == total,
        "summary": {
            "passed": passed,
            "failed": total - passed,
            "total": total,
        },
        "checks": [asdict(r) for r in results],
    }


def render_table(results: list[SmokeResult]) -> str:
    lines = ["No-paid demo smoke", ""]
    lines.append(f"{'check':<22} {'status':<7} {'ms':>5} endpoint")
    lines.append(f"{'-' * 22} {'-' * 7} {'-' * 5} {'-' * 48}")
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        code = str(result.status_code) if result.status_code is not None else "-"
        lines.append(
            f"{result.name:<22} {status:<7} {result.elapsed_ms:>5} "
            f"{result.path} ({code})"
        )
        if result.error:
            lines.append(f"  -> {result.error}")
    info = summarize(results)["summary"]
    lines.append("")
    lines.append(
        f"Summary: {info['passed']}/{info['total']} PASS, "
        f"{info['failed']} FAIL"
    )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run zero-cost local demo smoke checks.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact table.",
    )
    parser.add_argument(
        "--base-url",
        help=(
            "Probe a running local backend instead of in-process TestClient "
            "(example: http://127.0.0.1:8000)."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Per-request timeout in seconds for --base-url mode.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, out=None) -> int:
    args = _parse_args(argv)
    output = out or sys.stdout
    results = run_smoke(base_url=args.base_url, timeout=args.timeout)
    payload = summarize(results)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True), file=output)
    else:
        print(render_table(results), file=output)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
