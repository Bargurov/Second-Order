"""One-shot GET acquisition from SEC EDGAR for the approval named by this script's folder (see plan.json beside it).

Adapted from fcx-filings-01 (private; not in the public repository; itself adapted from copper-sec-01).
Runs only when plan.json carries a non-null approved_on. One GET per resource, in plan order: no redirects, no
retries, no cookies, no proxy, a new client per request, no other address, a pause of limits.pause_s between requests.
attempt-<n>.json is created exclusively before each request, outcome-<n>.json after it. A complete 200 of an accepted
media type (and, for JSON, a body that parses) is retained at the plan's target; anything else is recorded as it is
and nothing is retained. A 403/429 or a network failure stops the run.

The SEC asks automated clients to declare a contact in the User-Agent. The contact is read at request time from the
user-level environment variable SECOND_ORDER_FEED_CONTACT (Windows registry HKCU\\Environment), not from this process's
environment. It goes only into the User-Agent header: it is never printed, logged or written to any file, and the
records name only its source. Run: python -I acquire.py
"""
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

RUN = Path(__file__).resolve().parent
APPROVAL = RUN.name
REPO = RUN.parents[3]
CONTACT_TEMPLATE = "SecondOrder/0.1 (local research tool; contact from SECOND_ORDER_FEED_CONTACT, user level)"
NAMED = ("content-type", "content-encoding", "last-modified", "etag")


def now() -> str:
    return datetime.now().astimezone().isoformat()


def user_contact() -> str:
    """The user-level SECOND_ORDER_FEED_CONTACT, read from the registry now; empty when unset."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _kind = winreg.QueryValueEx(key, "SECOND_ORDER_FEED_CONTACT")
    except OSError:
        return ""
    return str(value).strip()


def write_new(path: Path, obj) -> None:
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")


def fetch(url: str, headers: dict, limits: dict, max_body: int):
    """(status, response_headers, body bytes, truncated, error)."""
    started = time.monotonic()
    body, truncated = bytearray(), False
    timeout = httpx.Timeout(connect=limits["connect_timeout_s"], read=limits["read_timeout_s"], write=10, pool=10)
    try:
        with httpx.Client(follow_redirects=False, trust_env=False, verify=True, timeout=timeout) as client:
            with client.stream("GET", url, headers=headers) as response:
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_body:
                        truncated = True
                        break
                    if time.monotonic() - started > limits["request_network_deadline_s"]:
                        return response.status_code, dict(response.headers), bytes(body), True, "deadline"
                return response.status_code, dict(response.headers), bytes(body), truncated, None
    except Exception as exc:  # recorded, never retried
        return None, {}, bytes(body), False, f"{type(exc).__name__}"


def body_ok(kind: str, body: bytes) -> bool:
    if kind == "json":
        try:
            json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return False
    return True


def main() -> int:
    plan = json.loads((RUN / "plan.json").read_text(encoding="utf-8"))
    if not plan.get("approved_on"):
        print("plan.json has no approved_on; nothing is requested")
        return 2
    contact = user_contact()
    if not contact:
        print("the user-level SECOND_ORDER_FEED_CONTACT is empty; nothing is requested")
        return 2
    headers = dict(plan["request_headers"])
    headers["User-Agent"] = f"SecondOrder/0.1 (local research tool; {contact})"
    limits = plan["limits"]
    first = True
    for res in plan["resources"]:
        n = res["n"]
        attempt_path, outcome_path = RUN / f"attempt-{n}.json", RUN / f"outcome-{n}.json"
        if attempt_path.exists() or outcome_path.exists():
            print(f"attempt {n} already exists; stopping")
            return 3
        if not first:
            time.sleep(limits["pause_s"])
        first = False
        write_new(attempt_path, {"approval_id": APPROVAL, "n": n, "url": res["url"], "kind": res["kind"],
                                 "state": "about_to_send", "recorded_at": now(), "user_agent": CONTACT_TEMPLATE})
        dispatched = now()
        status, rh, body, truncated, error = fetch(res["url"], headers, limits, res["max_body_bytes"])
        done = now()
        rh = {k.lower(): v for k, v in rh.items()}
        media = (rh.get("content-type") or "").split(";")[0].strip().lower() or None
        digest, size = hashlib.sha256(body).hexdigest(), len(body)
        outcome = "complete"
        if error:
            outcome = "network_error"
        elif status != 200:
            outcome = "not_200"
        elif truncated:
            outcome = "too_large"
        elif media not in res["accepted_media_types"]:
            outcome = "media_type_not_accepted"
        elif not body_ok(res["kind"], body):
            outcome = "body_not_expected_format"
        elif size == 0:
            outcome = "empty"
        record = {"n": n, "approval_id": APPROVAL, "url": res["url"], "kind": res["kind"], "outcome": outcome,
                  "http_status": status, "sha256": digest, "bytes": size, "hash_kind": "complete_response"
                  if outcome == "complete" else "partial_or_rejected_response", "retained": None,
                  "dispatched_at": dispatched, "body_completed_at": done, "media_type": media,
                  "named_headers": {k: rh.get(k) for k in NAMED if rh.get(k) is not None},
                  "contact_declared": True, "network_error": error, "truncated": truncated,
                  "max_body_bytes": res["max_body_bytes"]}
        if outcome == "complete":
            target = REPO / res["target"]
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "xb") as handle:
                handle.write(body)
            record["retained"] = res["target"]
        else:
            record["body_excerpt_hex_prefix"] = body[:64].hex()
            record["error_excerpt"] = body[:limits["error_excerpt_bytes"]].decode("utf-8", "replace")
        write_new(outcome_path, record)
        print(n, res["url"][-70:], status, size, outcome)
        if outcome == "network_error" or status in (403, 429):
            print("stopping the run")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
