"""The SYNTHETIC fixtures of the news contract (docs/news-usage-contract.md, user-api-0.4, served as user-api-0.5).

Not a test module. `build()` makes every fixture from the data owner's real functions (user_news, publication_import,
research_quality) over SYNTHETIC feeds and pages (tests/news_fakes.py), in a temporary folder with fixed clocks and a
fixed import ID, wrapped in this contract's envelopes; the limits and refusal examples are this contract's own
SYNTHETIC values (no numeric limit is selected by them). Nothing reaches a network or a provider.

    PYTHONPATH=".;tests" python tests/news_contract_fixtures.py   # news-contract-* fixtures and the new refusals
"""
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from account_fakes import World
from news_fakes import Pages, fed_link, fed_page, refreshed
from quality_cases import CASES
from second_order import publication_import, research_quality, user_news, user_research
from second_order.accounts import Identity

CONTRACT = "user-api-0.5"
FIXTURES = Path(__file__).resolve().parent.parent / "frontend" / "tests" / "fixtures"
DAY = {"day": "2026-10-14", "timezone": "Asia/Jerusalem", "resets_at": "2026-10-14T21:00:00+00:00"}
LABELS = {"search": "Searches", "import": "Publication imports", "source": "New sources",
          "preparation": "Prepared analyses"}
# SYNTHETIC limits for the examples only: the administrator types the real ones.
SET = {"search": (20, 4), "import": (5, 2), "source": (10, 3), "preparation": (10, 1)}


def quota(operation: str) -> dict:
    limit, used = SET[operation]
    return {"operation": operation, "label": LABELS[operation], "limit": limit, "used": used,
            "remaining": max(0, limit - used)}


def limits(state: str) -> dict:
    if state == "no_policy":
        return {"state": "no_policy", "detail": ("Searches, imports and new sources are not available yet: no usage "
                                                 "limits are set on this server. Ask the administrator."),
                "policy_version": None, **DAY,
                "operations": [{"operation": name, "label": label, "limit": None, "used": 0, "remaining": None}
                               for name, label in LABELS.items()],
                "storage": {"sources": {"used": 0, "limit": None}, "source_bytes": {"used": 0, "limit": None}},
                "rate": {"requests_per_minute": None, "concurrent_requests": None}}
    return {"state": "set", "detail": None, "policy_version": "usage-policy-1", **DAY,
            "operations": [quota(name) for name in LABELS],
            "storage": {"sources": {"used": 3, "limit": 200}, "source_bytes": {"used": 2_461, "limit": 5_000_000}},
            "rate": {"requests_per_minute": 120, "concurrent_requests": 4}}


def errors() -> dict:
    """One SYNTHETIC refusal per user-api-0.4 code, with the fields it carries."""
    def refusal(code: str, detail: str, **extra) -> dict:
        return {"contract": CONTRACT, "code": code, "detail": detail, **extra}
    resets = DAY["resets_at"]
    return {
        "no_usage_policy": refusal("no_usage_policy", "Searches, imports and new sources are not available yet: no "
                                   "usage limits are set on this server. Ask the administrator."),
        "usage_limit_reached": refusal("usage_limit_reached", "You have used today's searches. They reset at midnight "
                                       "in Asia/Jerusalem.", quota={"operation": "search", "limit": 20, "used": 20,
                                                                     **DAY}),
        "storage_limit_reached": refusal("storage_limit_reached", "This source would exceed what your account may "
                                         "hold. Nothing was saved.", storage={"measure": "source_bytes",
                                                                              "limit": 5_000_000, "used": 4_999_000,
                                                                              "adding": 2_461}),
        "fetch_budget_reached": refusal("fetch_budget_reached", "This server has made today's publication requests. "
                                        "Nothing was requested; you can paste the publication's text instead.",
                                        resets_at=resets),
        "request_key_reused": refusal("request_key_reused", "This search key was already used for another search. "
                                      "Nothing was counted."),
        "interests_changed": refusal("interests_changed", "Your interests were changed in another tab since this page "
                                     "loaded. Nothing was saved.", interests=interests(1)),
        "rate_limited": refusal("rate_limited", "Too many requests in a short time. Wait a moment, then read the page "
                                "again.", retry_after_seconds=20),
        "too_many_requests": refusal("too_many_requests", "Too many requests are in progress for your account. Wait "
                                     "for them to finish.", retry_after_seconds=1),
        "entry_changed": refusal("entry_changed", "The news entry changed since this page loaded. Reload the news.",
                                 requested=False),
        "import_unsupported": refusal("import_unsupported", "Importing the full publication is not available for this "
                                      "publisher yet. You can open the official page and paste its text into a new "
                                      "source instead.", paste_instead=True, requested=False),
        "publication_unavailable": refusal("publication_unavailable", "The publisher's page could not be read (HTTP "
                                           "503 from the publisher). You can open the official page and paste its "
                                           "text into a new source instead.", paste_instead=True, requested=True),
        "publication_time_conflict": refusal("publication_time_conflict", "The page's printed date disagrees with the "
                                             "feed's publication time, so neither is taken.", requested=True),
        "import_in_progress": refusal("import_in_progress", "This publication is being read now. Reload in a "
                                      "moment.", requested=False),
        "publication_changed": refusal("publication_changed", "The confirmation names another text than this import "
                                       "showed. Reload the import."),
        "import_interrupted": refusal("import_interrupted", "An earlier confirmation of this import stopped before it "
                                      "finished; nothing is created again. An administrator can check it."),
        "publication_unreadable": refusal("publication_unreadable", "The page could not be read as the release's "
                                          "text. You can open the official page and paste its text into a new source "
                                          "instead.", paste_instead=True, requested=True),
        "publication_too_long": refusal("publication_too_long", "The release has more than 50,000 characters and is "
                                        "never shortened. You can paste the part you need into a new source instead.",
                                        paste_instead=True, requested=True),
    }


def interests(version: int | None) -> dict:
    vocabulary = user_news.vocabulary()
    return {"vocabulary_version": vocabulary["vocabulary_version"], "rule": vocabulary["rule"],
            "vocabulary": vocabulary["interests"],
            "selected": ["monetary-policy", "energy"] if version else [], "version": version,
            "saved_at": "2026-10-14T08:55:00+00:00" if version else None}


def build() -> dict[str, dict]:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        world = World(root)
        world.standard_terms()
        folders = publication_import.Folders(inbox=root / "event-inbox", imports=root / "imports")
        refreshed(folders.inbox)
        fetcher = publication_import.PublicationFetcher(Pages({fed_link(1): (200, fed_page())}).transport())
        context = user_research.UserResearch(world.accounts, world.folders, world.sender(), world.clock)
        reader = Identity(world.ids["reader-a"], "reader-a", "reader-a (synthetic)", "user")
        chosen = ["monetary-policy", "energy"]
        by_interests = user_news.view(folders, reader, chosen, "interests")
        entry = next(row for row in by_interests["entries"] if row["import"]["state"] == "supported")
        searched = user_news.search(folders, reader, {"query": "synthetic", "interests": None, "sources": None,
                                                     "listing": "all"})
        with patch.object(publication_import.secrets, "token_hex", return_value="0123456789abcdef"):
            preview, _ = publication_import.prepare(folders, reader, entry["entry_id"], entry["version_sha256"],
                                                    fetcher, world.clock)
        confirmed, _ = publication_import.confirm(folders, context, reader, preview["import_id"],
                                                  {"text_sha256": preview["proposed_source"]["text_sha256"],
                                                   "confirm": True}, world.clock)
        everything = user_news.view(folders, reader, chosen, "all")
        empty = user_news.view(publication_import.Folders(inbox=root / "never-refreshed", imports=root / "imports"),
                               reader, chosen, "interests")
    recorded = json.loads((FIXTURES / "user-contract-analysis-recorded.json").read_text(encoding="utf-8"))
    from test_research_quality import read  # The research contract's own reading of a SYNTHETIC reply.
    headline, source, planted, _, _ = CASES["a number not in the source"]
    flagged = research_quality.assess(headline, source, read(source, planted)["analysis"])
    return {
        "news-contract-news": {"contract": CONTRACT, "news": by_interests},
        "news-contract-news-all": {"contract": CONTRACT, "news": everything},
        "news-contract-news-empty": {"contract": CONTRACT, "news": empty},
        "news-contract-interests": {"contract": CONTRACT, "interests": interests(1)},
        "news-contract-interests-none": {"contract": CONTRACT, "interests": interests(None)},
        "news-contract-interests-saved": {"contract": CONTRACT, "interests": interests(1), "changed": True},
        "news-contract-search": {"contract": CONTRACT, **searched, "counted": True, "quota": quota("search")},
        "news-contract-import-created": {"contract": CONTRACT, "import": preview, "created": True,
                                         "quota": quota("import")},
        "news-contract-import": {"contract": CONTRACT, "import": confirmed["import"]},
        "news-contract-import-confirmed": {"contract": CONTRACT, **confirmed, "created": True},
        "news-contract-limits": {"contract": CONTRACT, "limits": limits("set")},
        "news-contract-limits-no-policy": {"contract": CONTRACT, "limits": limits("no_policy")},
        "news-contract-quality": {"contract": CONTRACT,
                                  "quality": research_quality.for_user_analysis(recorded["analysis"])},
        "news-contract-quality-flagged": {"contract": CONTRACT, "quality": flagged},
        "news-contract-quality-none": {"contract": CONTRACT, "quality": None},
    }


def write() -> list[str]:
    written = []
    for name, payload in build().items():
        path = FIXTURES / f"{name}.json"
        path.write_bytes((json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        written.append(path.name)
    # The refusal examples join the user contract's, so every reader of user-contract-errors.json sees every code. The
    # news refusals are this generator's own and are rewritten; every other entry is kept as it is.
    path = FIXTURES / "user-contract-errors.json"
    held = json.loads(path.read_text(encoding="utf-8"))
    held.update(errors())
    path.write_bytes((json.dumps(held, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return written + [path.name]


if __name__ == "__main__":
    print("\n".join(write()))
