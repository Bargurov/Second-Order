"""QA cross-version check of QA-3's legacy review binding and the accounts store upgrade, on records the earlier server
itself wrote.

The owners' test builds a user-result-1 review by hand. This script instead runs the entry release's own code (37caa69,
given as a folder with its second_order and tests, for example from `git archive`) to sign in a SYNTHETIC reader, record
an analysis through the fake provider and save two reviews. It then opens the same folders with this checkout's code:
before `accounts upgrade`, after it, and through the user routes. It checks that every earlier row is kept, that no
record file changes on read, that the earlier reviews read as bound to the unchanged result, and that a page loaded
before the upgrade can still save its next review.

Everything is in a new temporary folder; nothing reaches a network or a real provider. Not a test module (unittest
never discovers it): it needs the earlier code.

    python tests/qa_legacy_upgrade.py --old <folder holding 37caa69's second_order and tests>
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

from fastapi.testclient import TestClient  # noqa: E402

from account_fakes import ACCOUNT, BASE, PASSWORDS, SESSION_WRITE, USER_WRITE  # noqa: E402
from second_order import accounts as acc  # noqa: E402
from second_order.api import create_app  # noqa: E402

EARLIER = r'''
import json, sys
from pathlib import Path
from account_fakes import USER_WRITE, World, source_form
root = Path(sys.argv[1])
world = World(root)
world.standard_terms(credits=40, limit=3)
client = world.client("reader-a")
source = client.post("/api/user/sources", headers=USER_WRITE, json=source_form()).json()["source"]["source_id"]
analysis = client.post("/api/user/analyses", headers=USER_WRITE,
                       json={"source_id": source, "effort": "high"}).json()["analysis"]["analysis_id"]
quote = client.post(f"/api/user/analyses/{analysis}/quotes", headers=USER_WRITE, json={}).json()["quote"]
ran = client.post(f"/api/user/analyses/{analysis}/runs", headers=USER_WRITE, json={
    "quote_id": quote["quote_id"], "effort": quote["effort"], "credits": quote["credits"], "approve": True})
assert ran.status_code == 201, ran.text
recorded = ran.json()["analysis"]
first = client.post(f"/api/user/analyses/{analysis}/reviews", headers=USER_WRITE, json={
    "parent_review_id": None, "result_sha256": recorded["result_sha256"], "status": "needs_revision",
    "notes": "SYNTHETIC first review, saved by the entry release."}).json()["review"]
second = client.post(f"/api/user/analyses/{analysis}/reviews", headers=USER_WRITE, json={
    "parent_review_id": first["review_id"], "result_sha256": recorded["result_sha256"], "status": "human_reviewed",
    "notes": "SYNTHETIC second review, saved by the entry release."}).json()["review"]
shown = client.get(f"/api/user/analyses/{analysis}").json()["analysis"]
print(json.dumps({"analysis_id": analysis, "result_sha256": recorded["result_sha256"],
                  "reviews": [first["review_id"], second["review_id"]], "contract": shown["contract"]
                  if "contract" in shown else None,
                  "review_hashes": [row["result_sha256"] for row in shown["reviews"]]}))
'''


def files(root: Path) -> dict[str, str]:
    """SHA-256 of every record file except the accounts store's own files."""
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file() and not path.name.startswith("accounts.db")}


def dump(store: Path) -> list[str]:
    connection = sqlite3.connect(store)
    try:
        return list(connection.iterdump())
    finally:
        connection.close()


def app(root: Path, moment: datetime):
    return create_app(root / "no-dossiers", None, root / "prepared-drafts", root / "reviews", root / "intake",
                      root / "attempts", paid=None, links=root / "links", research_analyses=root / "research-analyses",
                      accounts=root / "accounts" / "accounts.db", client_static=None, accounts_clock=lambda: moment,
                      inbox=root / "event-inbox")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--old", type=Path, required=True)
    args = parser.parse_args()
    checks: list[tuple[str, bool, str]] = []

    def check(label: str, passed: bool, detail: object = "") -> None:
        checks.append((label, bool(passed), str(detail)[:300]))

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        old = args.old.resolve()
        made = subprocess.run([sys.executable, "-c", EARLIER, str(root)], capture_output=True, text=True,
                              cwd=root, env={"PYTHONPATH": f"{old};{old / 'tests'}", "PYTHONDONTWRITEBYTECODE": "1",
                                             "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
        if made.returncode != 0:
            print(made.stderr[-2000:])
            return 2
        earlier = json.loads(made.stdout.strip().splitlines()[-1])
        store = root / "accounts" / "accounts.db"
        check("the earlier server wrote an accounts-2 store", acc.store_version(store) == "accounts-2",
              acc.store_version(store))
        check("the earlier server read its reviews as bound to its result",
              earlier["review_hashes"] == [earlier["result_sha256"]] * 2, earlier["review_hashes"])
        rows, record_files = dump(store), files(root)
        moment = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
        try:
            with TestClient(app(root, moment), base_url=BASE) as client:
                reply = client.post("/api/session/login", headers=SESSION_WRITE,
                                    json={"username": "reader-a", "password": PASSWORDS["reader-a"]})
                before_upgrade = f"{reply.status_code} {reply.text[:160]}"
        except Exception as exc:  # noqa: BLE001 - recorded as the observed behaviour
            before_upgrade = f"{type(exc).__name__}: {exc}"[:300]
        check("before the upgrade the new server refuses or works without changing the store (observed)",
              dump(store) == rows and files(root) == record_files, before_upgrade)
        upgraded = subprocess.run([sys.executable, "-m", "second_order", "accounts", "upgrade", "--accounts",
                                   str(store)], capture_output=True, text=True, cwd=HERE.parent)
        check("accounts upgrade succeeds", upgraded.returncode == 0, upgraded.stdout.strip() or upgraded.stderr[-300:])
        check("the store is accounts-3 after the upgrade", acc.store_version(store) == "accounts-3",
              acc.store_version(store))
        after = dump(store)
        kept = [row for row in rows if row.startswith("INSERT") and "accounts_meta" not in row]
        check("every earlier row is kept by the upgrade", all(row in after for row in kept),
              [row for row in kept if row not in after][:3])
        check("the upgrade changes no record file", files(root) == record_files)
        with TestClient(app(root, moment + timedelta(minutes=5)), base_url=BASE) as client:
            signed = client.post("/api/session/login", headers=SESSION_WRITE,
                                 json={"username": "reader-a", "password": PASSWORDS["reader-a"]})
            check("reader-a signs in after the upgrade", signed.status_code == 200, signed.text[:200])
            client.headers[ACCOUNT] = signed.json()["user"]["user_id"]
            reads = files(root)
            shown = client.get(f"/api/user/analyses/{earlier['analysis_id']}").json()["analysis"]
            check("reading changes no record file", files(root) == reads)
            check("the earlier reviews read as bound to the unchanged result",
                  [row["result_sha256"] for row in shown["reviews"]] == [shown["result_sha256"]] * 2,
                  {"shown": shown["result_sha256"], "reviews": [row["result_sha256"] for row in shown["reviews"]],
                   "earlier": earlier["result_sha256"]})
            check("the earlier reviews are the same versions",
                  [row["review_id"] for row in shown["reviews"]] == earlier["reviews"],
                  [row["review_id"] for row in shown["reviews"]])
            saved = client.post(f"/api/user/analyses/{earlier['analysis_id']}/reviews", headers=USER_WRITE, json={
                "parent_review_id": earlier["reviews"][-1], "result_sha256": earlier["result_sha256"],
                "status": "human_reviewed", "notes": "SYNTHETIC third review, from a page loaded before the upgrade."})
            check("a page loaded before the upgrade saves its next review", saved.status_code == 201, saved.text[:200])
            changed = {name for name, digest in files(root).items() if record_files.get(name) != digest}
            check("only the new review file was added; every earlier record file is unchanged",
                  all(name not in record_files for name in changed) and len(changed) == 1, sorted(changed))
            wrong = client.post(f"/api/user/analyses/{earlier['analysis_id']}/reviews", headers=USER_WRITE, json={
                "parent_review_id": saved.json()["review"]["review_id"], "result_sha256": "0" * 64,
                "status": "human_reviewed", "notes": "SYNTHETIC review against a result that was never shown."})
            check("a review against another result is still refused", (wrong.status_code, wrong.json().get("code"))
                  == (409, "result_changed"), wrong.text[:200])
    for label, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    failed = sum(1 for _, passed, _ in checks if not passed)
    print(f"{len(checks) - failed}/{len(checks)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
