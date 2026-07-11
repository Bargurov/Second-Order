"""test_environment_preflight.py

Canonical test-environment preflight: one deterministic probe that CI
and operators run after installing ``requirements-test.txt`` to verify
the backend suite's environment contract BEFORE interpreting any test
result.  It distinguishes environment/collection failures from genuine
product or test-contract failures.

Checks (all read-only; no provider, network, paid or DB call):

* every declared backend dependency imports, with its version reported;
* fastapi sits inside the verified compatibility bound (>=0.135,<0.137 —
  see requirements-test.txt for the bisect evidence);
* the five formerly uncollectable test modules import in a fresh
  subprocess (the missing-pytest defect the full-test audit found);
* the local/live-data gate is disabled in this environment (the default
  test universe cannot be silently widened);
* the probe itself neither creates nor modifies a root ``events.db``.

Exit code 0 only when every check passes.  ``--json`` output is
deterministic for a given installed environment.

Usage:
    python scripts/test_environment_preflight.py --json
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import-name -> reported-name for every package the backend suite needs
# at collection time.  uvicorn/streamlit are deliberately absent: nothing
# in the test suite imports them (uvicorn is the serving command).
_IMPORT_CHECKS: tuple[str, ...] = (
    "pytest",
    "fastapi",
    "starlette",
    "httpx",
    "pydantic",
    "numpy",
    "pandas",
    "yaml",
    "yfinance",
    "feedparser",
    "apscheduler",
    "dotenv",
    "telegram",
    "anthropic",
    "openai",
)

_FASTAPI_MIN = (0, 135)
_FASTAPI_MAX_EXCLUSIVE = (0, 137)

_FORMERLY_UNCOLLECTABLE: tuple[str, ...] = (
    "tests.test_news_clustering",
    "tests.test_reviewer_front_door",
    "tests.test_robust_diagnostics",
    "tests.test_track_record_scoring",
    "tests.test_reaction_profile_calibration_report",
)

_ROOT_DB = "events.db"
_SIDECARS = ("", "-wal", "-shm", "-journal")


def _root_db_stat() -> dict:
    out = {}
    for suffix in _SIDECARS:
        path = Path(_ROOT_DB + suffix)
        out[path.name] = (
            {"size": path.stat().st_size,
             "st_mtime_ns": path.stat().st_mtime_ns}
            if path.exists() else None
        )
    return out


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = []
    for chunk in version.split(".")[:3]:
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def build_report() -> dict:
    root_before = _root_db_stat()

    versions: dict[str, str] = {}
    import_failures: list[str] = []
    for name in _IMPORT_CHECKS:
        try:
            module = importlib.import_module(name)
        except Exception as exc:
            import_failures.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        versions[name] = str(
            getattr(module, "__version__", None)
            or getattr(module, "VERSION", "unknown")
        )

    fastapi_ok = False
    fastapi_version = versions.get("fastapi")
    if fastapi_version:
        vt = _version_tuple(fastapi_version)[:2]
        fastapi_ok = _FASTAPI_MIN <= vt < _FASTAPI_MAX_EXCLUSIVE

    module_import_failures: list[str] = []
    code = (
        "import sys; sys.path.insert(0, {root!r})\n"
        "import importlib\n"
        "for mod in {mods!r}:\n"
        "    importlib.import_module(mod)\n"
        "print('OK')\n"
    ).format(root=str(ROOT), mods=list(_FORMERLY_UNCOLLECTABLE))
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=600, cwd=str(ROOT),
    )
    if proc.returncode != 0 or "OK" not in proc.stdout:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        module_import_failures.append(tail[-1] if tail else "unknown failure")

    from tests import _local_data_gate as gate
    gate_disabled = not gate.local_data_opt_in()

    root_after = _root_db_stat()

    ok = (
        not import_failures
        and fastapi_ok
        and not module_import_failures
        and gate_disabled
        and root_before == root_after
    )
    return {
        "contract": "test-environment-preflight-v1",
        "ok": ok,
        "python": ".".join(str(v) for v in sys.version_info[:3]),
        "versions": dict(sorted(versions.items())),
        "import_failures": sorted(import_failures),
        "fastapi_within_supported_bound": fastapi_ok,
        "fastapi_supported_bound": ">=0.135,<0.137",
        "module_import_failures": module_import_failures,
        "local_data_gate_disabled": gate_disabled,
        "root_db_untouched": root_before == root_after,
    }


def main(argv: list[str] | None = None, *, out=None) -> int:
    parser = argparse.ArgumentParser(
        description="Canonical backend test-environment preflight "
                    "(read-only).")
    parser.add_argument("--json", action="store_true",
                        help="emit the structured JSON report")
    args = parser.parse_args(argv)
    output = out or sys.stdout

    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True), file=output)
    else:
        print(f"test-environment preflight: "
              f"{'OK' if report['ok'] else 'FAILED'}", file=output)
        for key in ("import_failures", "module_import_failures"):
            for item in report[key]:
                print(f"  {key}: {item}", file=output)
        print(f"  fastapi {report['versions'].get('fastapi', 'missing')} "
              f"within {report['fastapi_supported_bound']}: "
              f"{report['fastapi_within_supported_bound']}", file=output)
        print(f"  local-data gate disabled: "
              f"{report['local_data_gate_disabled']}", file=output)
        print(f"  root db untouched: {report['root_db_untouched']}",
              file=output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
