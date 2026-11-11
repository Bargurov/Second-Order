"""QA live-data smoke for the local current-news milestone (LOCAL_LIVE_SCOPE.md): ONE explicit refresh of the
allowlisted official feeds (second_order.event_inbox.SOURCES) into a new isolated cache, then a summary of what was
actually retrieved: per source its outcome, HTTP status, times, bytes and SHA-256, entry counts and whether each entry
carries a usable publication instant.

This makes real network requests, so it is not a test module (unittest never discovers it) and it runs only with
--confirm. It requests nothing outside the allowlist, follows no redirect, retries nothing and downloads no linked
article (event_inbox's own rules). It never reads the operator's contact: the fetcher has none, so the sources whose
publisher requires one (BLS) are reported "not_requested", a real outcome. The cache is a new folder under --root
(default data/private/qa-live, ignored by git); the operator's data/event-inbox is never touched.

    python tests/qa_live_smoke.py --confirm
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from second_order import event_inbox  # noqa: E402


def summary(result: dict, cache: Path, started: str) -> dict:
    sources = []
    for source in result["sources"]:
        success, attempt = source["last_success"], source["last_attempt"]
        entries = [item for item in result["items"] if item["source"] == source["key"]]
        instants = [item["feed_timestamp"]["instant_utc"] for item in entries if item["feed_timestamp"]["instant_utc"]]
        sources.append({
            "key": source["key"], "publisher": source["publisher"], "category": source["category"],
            "state": source["state"], "http_status": attempt and attempt["http_status"],
            "started_at": attempt and attempt["started_at"], "finished_at": attempt and attempt["finished_at"],
            "retrieved_at": success and success["retrieved_at"], "bytes": success and success["bytes"],
            "sha256": success and success["sha256"], "listed": success and success["listed"],
            "kept": success and success["item_count"], "skipped": success and success["skipped_count"],
            "with_instant": len(instants), "without_instant": len(entries) - len(instants),
            "newest_instant": max(instants) if instants else None,
            "timestamp_problems": sorted({item["feed_timestamp"]["problem"].split(",")[0]
                                          for item in entries if item["feed_timestamp"]["problem"]}),
            "entries": [{"title": item["title"], "link": item["link"], "raw_timestamp": item["feed_timestamp"]["raw"],
                         "instant_utc": item["feed_timestamp"]["instant_utc"],
                         "excerpt_characters": len(item.get("excerpt") or "")} for item in entries]})
    return {"smoke": "qa-live-smoke-1", "started_at": started, "cache": str(cache),
            "outcomes": [{key: outcome.get(key) for key in ("source", "outcome", "detail")}
                         for outcome in result["refreshed"]], "sources": sources}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--confirm", action="store_true", help="make the real requests (required)")
    parser.add_argument("--root", type=Path, default=Path("data/private/qa-live"))
    args = parser.parse_args()
    if not args.confirm:
        parser.error("this makes real requests to the allowlisted official feeds; pass --confirm to run it")
    started = datetime.now(timezone.utc)
    cache = args.root / f"refresh-{started.strftime('%Y%m%dT%H%M%SZ')}" / "event-inbox"
    cache.mkdir(parents=True)  # A new folder each run: an earlier cache is never refreshed over.
    result = event_inbox.refresh(cache, event_inbox.FeedFetcher(contact=None))
    shown = summary(result, cache, started.isoformat())
    (cache.parent / "qa-summary.json").write_text(json.dumps(shown, indent=1, ensure_ascii=False), encoding="utf-8")
    for source in shown["sources"]:
        print(f"{source['key']:<20} {source['state']:<14} http {source['http_status']}  kept {source['kept']}  "
              f"with instant {source['with_instant']}  newest {source['newest_instant']}")
    print(f"summary: {cache.parent / 'qa-summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
