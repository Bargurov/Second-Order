"""The SYNTHETIC fixtures of the stories contract (docs/news-stories-contract.md, user-api-0.5).

Not a test module. `build()` makes every fixture from the real functions (news_views, story_deeper) over SYNTHETIC
publishers and feeds (tests/news_desk_fakes.py), grouped, curated and briefed in a temporary folder with a fixed clock,
wrapped in this contract's envelopes; the refusal examples are this contract's own. Nothing reaches a network.

    PYTHONPATH=".;tests" python tests/stories_contract_fixtures.py   # stories-contract-* fixtures and the refusals
"""
import json
from pathlib import Path
import tempfile

from account_fakes import World
from news_desk_fakes import (FACT_TITLE, REVISION, START, TARIFF, UNRELATED, Feeds, assess, curate, desk_in,
                             index_desk, publish_wire, text_desk, trade_feeds, wire_item)
from second_order import news_feeds, news_views, story_deeper
from second_order.accounts import Identity
from second_order.user_research import UNMARKED, UserResearch

CONTRACT = "user-api-0.5"
FIXTURES = Path(__file__).resolve().parent.parent / "frontend" / "tests" / "fixtures"
class Setup:
    """Accounts with SYNTHETIC terms and the curated SYNTHETIC newsroom of tests/news_desk_fakes.py (curate)."""

    def __init__(self, root: Path):
        self.world = World(root)
        self.world.standard_terms()
        self.desk = desk_in(root, network=Feeds(trade_feeds(START)))
        synthetic = [publisher for publisher in self.desk.publishers.values() if publisher.synthetic]
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher, synthetic, lambda: START)
        self.ids = curate(self.desk, START, "fixture-admin")
        self.topic_id = self.ids["topic_id"]
        self.reader = Identity(self.world.ids["reader-a"], "reader-a", "reader-a (synthetic)", "user")
        self.context = UserResearch(self.world.accounts, self.world.folders, self.world.sender(), self.world.clock)

    def found(self) -> dict:
        return news_views.world(self.desk, START)

    def story(self, title: str) -> str:
        return next(story_id for story_id, story in self.found()["stories"].items()
                    if any(row["title"] == title for row in story["reports"]))


def errors() -> dict:
    def refusal(code: str, detail: str, **extra) -> dict:
        return {"contract": CONTRACT, "code": code, "detail": detail, **extra}
    return {
        "story_changed": refusal("story_changed", "This story's material changed since the page was read. Nothing was "
                                 "saved; read it again to see what would be used now."),
        "deeper_unavailable": refusal("deeper_unavailable", "A deeper analysis needs material its publishers allow to "
                                      "be analysed; this story's reports grant no such use."),
        "newsroom_unreadable": refusal("newsroom_unreadable", "The news could not be read on this server. An "
                                       "administrator can check it."),
        "source_unmarked": refusal("source_unmarked", UNMARKED),
    }


def build() -> dict[str, dict]:
    with tempfile.TemporaryDirectory() as folder:
        setup = Setup(Path(folder))
        desk = setup.desk
        tariff, revision = setup.story(TARIFF), setup.story(REVISION)
        port = setup.story("Synthetic port reports record container volumes")
        merged = next(iter(setup.found()["folded"]["merged_into"]))
        preview = story_deeper.preview(desk, setup.context, setup.reader, tariff, START)
        done, created = story_deeper.start(desk, setup.context, setup.reader, tariff, json.dumps({
            "material_sha256": preview["material_sha256"], "effort": "low"}).encode(), START)
        again = story_deeper.preview(desk, setup.context, setup.reader, tariff, START)
        fixtures = {
            "stories-contract-hot": {"contract": CONTRACT, "stories": news_views.stories_view(desk, "hot", [], START)},
            "stories-contract-coverage": {"contract": CONTRACT,
                                          "stories": news_views.stories_view(desk, "coverage", [], START)},
            "stories-contract-latest": {"contract": CONTRACT,
                                        "stories": news_views.stories_view(desk, "latest", [], START)},
            "stories-contract-interests": {"contract": CONTRACT, "stories": news_views.stories_view(
                desk, "interests", ["trade"], START)},
            "stories-contract-story": {"contract": CONTRACT, "story": news_views.story_view(desk, tariff, START)},
            "stories-contract-story-nobrief": {"contract": CONTRACT,
                                               "story": news_views.story_view(desk, revision, START)},
            "stories-contract-story-notime": {"contract": CONTRACT, "story": news_views.story_view(desk, port, START)},
            "stories-contract-story-merged": {"contract": CONTRACT, "story": news_views.story_view(desk, merged, START)},
            "stories-contract-story-outside": {"contract": CONTRACT, "story": news_views.story_view(
                desk, setup.story(UNRELATED), START)},
            "stories-contract-topics": {"contract": CONTRACT, "topics": news_views.topics_view(desk, START)},
            "stories-contract-topic": {"contract": CONTRACT, "topic": news_views.topic_view(desk, setup.topic_id,
                                                                                            START)},
            "stories-contract-deeper": {"contract": CONTRACT, "deeper": preview},
            "stories-contract-deeper-existing": {"contract": CONTRACT, "deeper": again},
            "stories-contract-deeper-done": {"contract": CONTRACT, "deeper": done, "created": created},
        }
        texts, _ = text_desk(Path(folder) / "texts")  # SYNTHETIC White House pages, their texts retrieved.
        fixtures["stories-contract-hot-unassessed"] = {"contract": CONTRACT, "stories": news_views.stories_view(
            texts, "hot", [], START)}  # Before any assessment: nothing listed, every current headline awaiting.
        assess(texts, START)
        stories = news_views.world(texts, START)["stories"]
        fact = next(story_id for story_id, story in stories.items() if story["title"] == FACT_TITLE)
        fixtures["stories-contract-story-text"] = {"contract": CONTRACT, "story": news_views.story_view(
            texts, fact, START)}
        fixtures["stories-contract-deeper-text"] = {"contract": CONTRACT, "deeper": story_deeper.preview(
            texts, setup.context, setup.reader, fact, START)}
        fixtures["stories-contract-latest-text"] = {"contract": CONTRACT, "stories": news_views.stories_view(
            texts, "latest", [], START)}
        indexed, indexed_story = index_desk(Path(folder) / "indexed")  # A SIMULATED news index's coverage.
        fixtures["stories-contract-story-indexed"] = {"contract": CONTRACT, "story": news_views.story_view(
            indexed, indexed_story, START)}
        empty = desk_in(Path(folder) / "empty")
        fixtures["stories-contract-empty"] = {"contract": CONTRACT,
                                              "stories": news_views.stories_view(empty, "hot", [], START)}
        # A brief that records who says what (story-brief-0.4) about an opened procedure (econ-explanation-0.5), on
        # its own desk so the other fixtures stay as they are.
        claims = desk_in(Path(folder) / "claims", network=Feeds(trade_feeds(START, courier_extra=[wire_item(START)])))
        news_feeds.refresh(claims.feeds, claims.fetcher, [row for row in claims.publishers.values() if row.synthetic],
                           lambda: START)
        curate(claims, START, "fixture-admin")
        fixtures["stories-contract-story-claims"] = {"contract": CONTRACT, "story": news_views.story_view(
            claims, publish_wire(claims, START), START)}
    return fixtures


def write() -> list[str]:
    written = []
    for name, payload in build().items():
        path = FIXTURES / f"{name}.json"
        path.write_bytes((json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        written.append(path.name)
    path = FIXTURES / "user-contract-errors.json"
    held = json.loads(path.read_text(encoding="utf-8"))
    held.update(errors())
    path.write_bytes((json.dumps(held, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return written + [path.name]


if __name__ == "__main__":
    print("\n".join(write()))
