#!/usr/bin/env python3
"""Demo API smoke for the four ``/demo/*`` endpoints.

Read-only smoke that probes the four demo backend endpoints and
reports HTTP status, ``section`` value, and envelope shape for each.
Two modes:

* **In-process (default).**  Builds a FastAPI ``TestClient`` against
  ``api.app`` and calls the endpoints directly.  No network access,
  no port binding.
* **Base URL (``--base-url``).**  Issues HTTP GET requests against a
  running uvicorn (or other ASGI) server.  Uses ``urllib`` from
  stdlib — no extra dependency.

Read-only by construction
-------------------------

* No DB reads or writes by the smoke itself.  The endpoints the
  smoke calls are themselves read-only demo surfaces.
* No ``yfinance`` / ``market_data`` / paid provider / LLM import or
  call.  No network access in the default in-process mode.
* No mutation of ``artifacts/``, ``news_inbox.json``, the events DB,
  or any cache.  The smoke only reads endpoint responses.
* ``--output`` is the only filesystem side effect, and only when
  explicitly passed.  The script refuses to overwrite an existing
  output path.

Output contract (JSON)::

    {
      "ok":                bool,
      "base_url":          str,   # "" in in-process mode
      "mode":              "in_process" | "base_url",
      "endpoints_checked": int,
      "results": [
        {
          "path":                  str,
          "status_code":           int | null,
          "ok":                    bool,
          "section":               str | null,
          "count":                 int | null,    # if present on body
          "required_keys_present": bool,
          "missing_keys":          [str, ...],
          "error":                 str | null,
        },
        ...
      ],
      "warnings":          [str, ...],
      "errors":            [str, ...],
    }

The envelope ``ok`` is ``True`` iff every endpoint:

* returned HTTP 200, AND
* deserialised as a JSON object, AND
* carried the expected ``section`` literal, AND
* carried every required envelope key.

An endpoint that reaches HTTP 200 with a well-shaped envelope but
declares ``errors`` on its body (e.g., the Evidence Summary endpoint
when its artifact file is missing) is **not** a smoke failure — the
endpoint-level errors are surfaced verbatim under the result's
``error`` field so the operator can see them without the smoke
crashing.

Conservative wording — the smoke never claims the demo endpoints are
production-graded, correct, validated, or fit to trade.  It only
reports response shape.

Usage::

    python scripts/demo_api_smoke.py            # in-process, text
    python scripts/demo_api_smoke.py --json
    python scripts/demo_api_smoke.py --base-url http://127.0.0.1:8000
    python scripts/demo_api_smoke.py --json \\
        --output /tmp/demo_api_smoke.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Per-endpoint expectation table.  The required key set pins each
# source module's envelope contract so the smoke catches a silently
# dropped field even when HTTP 200 + section are correct.
_ENDPOINTS: tuple[dict[str, Any], ...] = (
    {
        "path":     "/demo/daily-market",
        "section":  "daily",
        "required": (
            "ok", "section", "items", "count",
            "skipped_artifacts", "warnings", "errors",
        ),
    },
    {
        "path":     "/demo/weekly-market",
        "section":  "weekly",
        "required": (
            "ok", "section", "items", "count",
            "duplicate_groups_collapsed", "warnings", "errors",
        ),
    },
    {
        "path":     "/demo/still-moving-market",
        "section":  "still_moving",
        "required": (
            "ok", "section", "items", "count",
            "rejected_count", "rejection_summary",
            "warnings", "errors",
        ),
    },
    {
        "path":     "/demo/evidence-summary",
        "section":  "evidence_summary",
        "required": (
            "ok", "section", "cohort_summary", "verdict_counts",
            "fdr_significant_count", "raw_p_candidate_count",
            "benchmark_sensitivity_status", "limitations",
            "warnings", "errors",
        ),
    },
)


FetchFn = Callable[[str], "tuple[int, str]"]


# ---------------------------------------------------------------------------
# Fetch backends — kept narrow so tests can inject a deterministic fake.
# ---------------------------------------------------------------------------


def _in_process_fetch_factory() -> FetchFn:
    """Return a ``fetch(path) -> (status_code, body_text)`` callable
    backed by a FastAPI ``TestClient`` over ``api.app``.

    The ``api`` import is lazy so importing this module does not
    spin up the FastAPI app (and its lifespan-startup background
    tasks) until the smoke actually runs.
    """
    import api as _api  # noqa: PLC0415 — intentional lazy import
    from fastapi.testclient import TestClient  # noqa: PLC0415

    client = TestClient(_api.app)

    def fetch(path: str) -> tuple[int, str]:
        r = client.get(path)
        return r.status_code, r.text

    return fetch


def _http_fetch_factory(base_url: str, *, timeout: float = 10.0) -> FetchFn:
    """Return a ``fetch(path) -> (status_code, body_text)`` callable
    that issues HTTP GETs against ``base_url`` via ``urllib``.

    Uses stdlib only — no ``requests`` / ``httpx`` dependency.
    """
    import urllib.error    # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    base = base_url.rstrip("/")

    def fetch(path: str) -> tuple[int, str]:
        url = f"{base}{path}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return int(resp.status), resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8")
            except Exception:  # noqa: BLE001
                body = ""
            return int(e.code), body

    return fetch


# ---------------------------------------------------------------------------
# Per-endpoint shape check
# ---------------------------------------------------------------------------


def _check_endpoint(
    *,
    fetch: FetchFn,
    path: str,
    expected_section: str,
    required_keys: Sequence[str],
) -> dict[str, Any]:
    """Probe one endpoint and produce a single result dict.

    The result dict ``ok`` is ``True`` iff:

    * HTTP status was 200, AND
    * body parsed as a JSON object, AND
    * ``body['section']`` equalled ``expected_section``, AND
    * every key in ``required_keys`` was present.

    Body-level ``errors`` (declared on the envelope itself, e.g., the
    Evidence Summary endpoint reporting a missing artifact) are
    surfaced verbatim under ``error`` but do not flip the result's
    ``ok`` field — the endpoint reached us with a valid envelope.
    """
    result: dict[str, Any] = {
        "path":                  path,
        "status_code":           None,
        "ok":                    False,
        "section":               None,
        "count":                 None,
        "required_keys_present": False,
        "missing_keys":          [],
        "error":                 None,
    }

    try:
        status, body_text = fetch(path)
    except Exception as e:  # noqa: BLE001 — surface, do not crash
        result["error"] = f"fetch_failed: {type(e).__name__}: {e}"
        return result

    result["status_code"] = status

    if status != 200:
        result["error"] = f"unexpected_status: {status}"
        return result

    try:
        body = json.loads(body_text)
    except json.JSONDecodeError as e:
        result["error"] = f"json_decode_failed: {e}"
        return result

    if not isinstance(body, dict):
        result["error"] = f"body_not_dict: {type(body).__name__}"
        return result

    section = body.get("section")
    result["section"] = section if isinstance(section, str) else None
    section_ok = (section == expected_section)

    missing = [k for k in required_keys if k not in body]
    result["missing_keys"] = missing
    result["required_keys_present"] = not missing

    count = body.get("count")
    if isinstance(count, int) and not isinstance(count, bool):
        result["count"] = count

    body_errors = body.get("errors")
    if isinstance(body_errors, list) and body_errors:
        # Surface endpoint-declared errors verbatim — these include
        # the Evidence Summary "missing artifact" path the spec
        # singles out.  They do not crash the smoke.
        result["error"] = "; ".join(str(e) for e in body_errors)

    shape_ok = section_ok and not missing
    if not section_ok and result["error"] is None:
        result["error"] = (
            f"section_mismatch: expected={expected_section!r} "
            f"got={section!r}"
        )
    if missing and result["error"] is None:
        result["error"] = f"missing_keys: {missing}"

    result["ok"] = shape_ok
    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_demo_api_smoke(
    *,
    base_url: str | None = None,
    fetch: FetchFn | None = None,
) -> dict[str, Any]:
    """Run the demo API smoke.

    Parameters
    ----------
    base_url
        Optional base URL for a running ASGI server.  When omitted
        AND ``fetch`` is also omitted, the smoke runs in-process via
        ``fastapi.testclient.TestClient``.
    fetch
        Optional callable that takes a path and returns a
        ``(status_code, body_text)`` tuple.  Useful for tests that
        want to drive the smoke against a deterministic seam.  When
        supplied, ``base_url`` is informational only — the mode field
        still reports ``base_url`` if a value was provided, otherwise
        ``in_process``.
    """
    warnings: list[str] = []
    errors:   list[str] = []

    if fetch is None:
        if base_url:
            try:
                fetch = _http_fetch_factory(base_url)
            except Exception as e:  # noqa: BLE001
                return _envelope_after_setup_failure(
                    base_url=base_url, mode="base_url",
                    errors=[
                        f"http_fetch_setup_failed: {type(e).__name__}: {e}",
                    ],
                )
            mode = "base_url"
        else:
            try:
                fetch = _in_process_fetch_factory()
            except Exception as e:  # noqa: BLE001
                return _envelope_after_setup_failure(
                    base_url=base_url, mode="in_process",
                    errors=[
                        f"test_client_setup_failed: "
                        f"{type(e).__name__}: {e}",
                    ],
                )
            mode = "in_process"
    else:
        mode = "base_url" if base_url else "in_process"

    results: list[dict[str, Any]] = []
    for endpoint in _ENDPOINTS:
        results.append(_check_endpoint(
            fetch=fetch,
            path=endpoint["path"],
            expected_section=endpoint["section"],
            required_keys=endpoint["required"],
        ))

    return {
        "ok":                all(r["ok"] for r in results),
        "base_url":          base_url or "",
        "mode":              mode,
        "endpoints_checked": len(_ENDPOINTS),
        "results":           results,
        "warnings":          warnings,
        "errors":            errors,
    }


def _envelope_after_setup_failure(
    *,
    base_url: str | None,
    mode: str,
    errors: list[str],
) -> dict[str, Any]:
    """Build the envelope returned when fetch-backend setup itself
    failed (e.g., ``import api`` raised) so the smoke does not crash
    the caller.
    """
    return {
        "ok":                False,
        "base_url":          base_url or "",
        "mode":              mode,
        "endpoints_checked": 0,
        "results":           [],
        "warnings":          [],
        "errors":            list(errors),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, indent=2, sort_keys=True, default=str)


def _render_text(envelope: dict[str, Any]) -> str:
    lines: list[str] = ["Demo API smoke", ""]
    lines.append(f"OK:        {envelope['ok']}")
    lines.append(f"Mode:      {envelope['mode']}")
    lines.append(f"Base URL:  {envelope['base_url'] or '-'}")
    lines.append(f"Checked:   {envelope['endpoints_checked']}")
    lines.append("")
    for r in envelope["results"]:
        status_part = (
            f"status={r['status_code']}"
            if r["status_code"] is not None else "status=-"
        )
        section_part = (
            f"section={r['section']!r}"
            if r["section"] else "section=-"
        )
        ok_part = "OK" if r["ok"] else "FAIL"
        lines.append(
            f"  [{ok_part}] {r['path']} ({status_part}, {section_part})"
        )
        if r.get("count") is not None:
            lines.append(f"      count={r['count']}")
        if r.get("missing_keys"):
            lines.append(f"      missing_keys={r['missing_keys']}")
        if r.get("error"):
            lines.append(f"      error={r['error']}")
    if envelope.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for w in envelope["warnings"]:
            lines.append(f"  - {w}")
    if envelope.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for e in envelope["errors"]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only smoke for the four /demo/* backend endpoints. "
            "Defaults to in-process TestClient mode against api.app; "
            "pass --base-url to call a running ASGI server instead."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of the compact text view.",
    )
    parser.add_argument(
        "--base-url", dest="base_url", default=None,
        help=(
            "Optional base URL (e.g., http://127.0.0.1:8000) — when "
            "supplied, the smoke issues HTTP GETs via urllib instead "
            "of using the in-process TestClient."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  Refuses "
            "to overwrite an existing file."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _write_output(
    *,
    envelope: dict[str, Any],
    output_path: str,
) -> str | None:
    """Write the JSON envelope to ``output_path``.  Returns an error
    string when the path already exists or the write fails; returns
    ``None`` on success.
    """
    p = Path(output_path)
    if p.exists():
        return (
            f"--output path already exists; refusing to overwrite: "
            f"{output_path}"
        )
    try:
        p.write_text(_render_json(envelope), encoding="utf-8")
    except OSError as e:
        return f"failed to write --output {output_path}: {e}"
    return None


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    envelope = run_demo_api_smoke(base_url=args.base_url)

    if args.output_path:
        write_err = _write_output(
            envelope=envelope, output_path=args.output_path,
        )
        if write_err:
            envelope["errors"].append(write_err)
            envelope["ok"] = False

    if args.json:
        print(_render_json(envelope), file=output)
    else:
        print(_render_text(envelope), file=output)
    return 0 if envelope["ok"] else 1


__all__: tuple[str, ...] = (
    "run_demo_api_smoke",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
