"""The research notes of the metals page (metals_research): the committed content's shape, and each link resolved
against the figures on the page or the copper thesis's passages.

The USGS and IEA figures here come from the SYNTHETIC rows and sheets of tests/metals_fakes.py; the passages are made-up
entries in the shape thesis_view.passages returns. Only the committed content file and the committed copper thesis's
version file (content only: no retained source is read) are real.
"""
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

import fcx_fakes
import metals_fakes
from second_order import metals_iea_uses, metals_research, metals_risk, metals_usgs, metals_view, thesis_schema
from second_order.metals_research import ResearchRefused

WRITTEN_BY = ("Written by the assistant from the figures on this page and retained sources; not reviewed by the "
              "owner.")
TONS = "metric tons"
# Claim words no text of the research notes may use: case-insensitive, at the start of a word.
CLAIM_WORDS = re.compile(r"\b(?:buy|sell|recommend|forecast|predict|will\b|price will|caus(?:e|es|ed|ing))", re.I)
REAL_PASSAGES = ["usgs26-end-uses", "usgs26-substitutes", "mli-aluminum-2025", "usgs26-scrap-share", "usgs26-recycling",
                 "usgs26-mine-events", "fcx-mud-rush-2025", "mli-pass-through-2025"]


def rows():
    """The synthetic USGS rows, plus a plain-number 2025 reliance for copper and two 2025 reserves series for zinc
    (with no production series to pair with)."""
    found = metals_fakes.usgs_rows()
    found.append(metals_fakes._row("COPPER", "Copper", "United States", "Net import reliance",
                                   "Net import reliance as a percentage of apparent consumption", "percent", "2025",
                                   "57", section=metals_fakes.SALIENT, critical="No"))
    for ore in ("Ore A", "Ore B"):
        found += metals_fakes._table("ZINC", "Zinc", "Reserves", "Reserves: " + ore, "Reserves: " + ore + ", rounded",
                                     TONS, "2025", [("Alpha", "10")], "100")
    return found


def evidence(passage_id, state="verified"):
    """A passage as thesis_view.passages returns it (made up). A verified quote holds every date the real events give
    ("2025", "September 2025", "November 2026"), so an event citing it passes the date check."""
    verified = state == "verified"
    quote = "Synthetic quote of " + passage_id + ", in September 2025 and November 2026."
    return {"id": passage_id, "source": "usgs-2026", "title": "Synthetic Summaries 2026: Copper",
            "publisher": "Synthetic Survey", "edition": "2026", "edition_date": "2026-02-01",
            "quote": quote if verified else None,
            "where": "page 1 (transcribed from the PDF)", "state": state,
            "problem": None if verified else "usgs-2026: Synthetic detail of a " + state + " source."}


def chain(links, chain_id="synthetic-chain"):
    return {"id": chain_id, "title": "Synthetic chain title", "disruption": "Synthetic disruption text.",
            "links": links, "direct": ["Synthetic direct party"], "indirect": ["Synthetic indirect party"],
            "gains_losses": [{"who": "Synthetic producers elsewhere", "direction": "may gain",
                              "mechanism": "Synthetic mechanism text."}],
            "mitigants": ["Synthetic mitigant"], "learned": "Synthetic: what is measured.",
            "assumed": "Synthetic: what is assumed."}


def measured(ref):
    return {"text": "Synthetic measured link", "kind": "measured", "ref": ref}


def content(metals):
    return {"research_version": metals_research.VERSION, "written_by": WRITTEN_BY, "metals": metals}


def real():
    return metals_research.load(metals_view.METALS_DIR)


def real_passages(body):
    """A verified made-up passage for every reference the notes cite, copper thesis and FCX alike."""
    return {ref: evidence(ref.split(":", 1)[1]) for ref in metals_research.passage_refs(body)}


def strings(value, found):
    """Every string in a JSON value, keys included."""
    if isinstance(value, dict):
        for key, item in value.items():
            found.append(key)
            strings(item, found)
    elif isinstance(value, list):
        for item in value:
            strings(item, found)
    elif isinstance(value, str):
        found.append(value)
    return found


class Inputs(unittest.TestCase):
    def setUp(self):
        self.rows = rows()
        self.chapters = metals_usgs.read(self.rows)
        self.risk = metals_risk.read(self.chapters, self.rows)
        sheets = metals_fakes.iea_uses_sheets()
        self.uses = metals_iea_uses.read(sheets[metals_iea_uses.BY_MINERAL], sheets[metals_iea_uses.BY_TECH])

    def resolve(self, body, passages=None, **withheld):
        keyed = {name if ":" in name else "copper:" + name: item for name, item in (passages or {}).items()}
        return metals_research.resolve(body, self.chapters, self.risk, self.uses, keyed, **withheld)


class ContentTests(Inputs):
    def test_the_real_content_validates_and_cites_passages_of_the_copper_thesis(self):
        body = real()
        self.assertEqual(body["research_version"], metals_research.VERSION)
        self.assertEqual(body["written_by"], WRITTEN_BY)
        self.assertEqual(list(body["metals"]), ["copper", "cobalt", "lithium", "rare-earths", "nickel", "aluminum"])
        ids = metals_research.passage_ids(body)
        self.assertEqual(ids, REAL_PASSAGES)  # First use first, each once.
        index = thesis_schema.load_index("copper")
        thesis = thesis_schema.load_version("copper", len(index["versions"]))
        self.assertLessEqual(set(ids), {item["id"] for item in thesis["passages"]})
        fcx = [ref for ref in metals_research.passage_refs(body) if ref.startswith("fcx:")]
        self.assertEqual(fcx, ["fcx:q3-p-bagdad-approval"])  # The one register event from the FCX research.
        resolved = self.resolve(body, real_passages(body))
        links = [link for metal in resolved["metals"].values() for item in metal["chains"] for link in item["links"]]
        self.assertEqual({link["kind"] for link in links}, {"measured", "stated", "hypothesis"})
        for link in links:
            if link["kind"] == "measured":  # Exactly one of the two.
                self.assertNotEqual(link["shown"] is None, link["unavailable"] is None, link)
            elif link["kind"] == "stated":
                self.assertEqual(link["evidence"]["state"], "verified")

    def test_no_text_of_the_real_content_uses_a_claim_word(self):
        text = strings(real(), [])
        self.assertGreater(len(text), 100)
        self.assertEqual([item for item in text if CLAIM_WORDS.search(item)], [])

    def test_the_claim_word_guard_catches_each_word(self):
        for caught in ("Buyers wait", "We sell", "selling", "recommended", "A forecast", "predicts", "it will rise",
                       "the price will", "causes", "Caused", "causing", "cause"):
            self.assertIsNotNone(CLAIM_WORDS.search(caught), caught)
        for passed in ("because", "willing", "goodwill", "unpredictable"):
            self.assertIsNone(CLAIM_WORDS.search(passed), passed)

    def test_the_fixed_texts(self):
        self.assertEqual(metals_research.ENGINE, "metals-research-0.3")
        self.assertEqual(metals_view.VIEW_VERSION, "metals-view-0.5")
        self.assertEqual(metals_research.WRITTEN_BY, WRITTEN_BY)
        self.assertEqual(metals_research.RESEARCH_PROBLEM, "The research notes are not in the shape this version reads")

    def test_the_file_must_be_there_and_strict_json(self):
        folder = Path(tempfile.mkdtemp(prefix="second-order-metals-research-"))
        self.addCleanup(shutil.rmtree, folder, True)
        for name, data in (("missing", None), ("repeated key", b'{"metals": {}, "metals": {}}'),
                           ("not UTF-8", b'{"a": "caf\xe9"}'), ("NaN", b'{"a": NaN}')):
            with self.subTest(name):
                path = folder / "research.json"
                path.unlink(missing_ok=True)
                if data is not None:
                    path.write_bytes(data)
                with self.assertRaises(ResearchRefused) as raised:
                    metals_research.load(folder)
                self.assertEqual(raised.exception.place, "research.json")

    def refused(self, change, place):
        body = real()
        change(body)
        with self.assertRaises(ResearchRefused) as raised:
            metals_research.validate(body)
        self.assertEqual(raised.exception.place, place)
        self.assertTrue(raised.exception.rule)
        with self.assertRaises(ResearchRefused):  # resolve validates too.
            self.resolve(body, {name: evidence(name) for name in REAL_PASSAGES})

    def test_schema_refusals_name_the_place(self):
        copper = "metals.copper"
        cc = copper + ".chains[0]"

        def link(index, value):
            return lambda body: body["metals"]["copper"]["chains"][0]["links"].__setitem__(index, value)

        def set_in(path, value):
            def change(body):
                target = body
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
            return change

        def delete(path):
            def change(body):
                target = body
                for key in path[:-1]:
                    target = target[key]
                del target[path[-1]]
            return change
        chain0 = ["metals", "copper", "chains", 0]
        cases = {
            "no version": (delete(["research_version"]), "research.json"),
            "an extra top field": (set_in(["notes"], "Synthetic extra field"), "research.json"),
            "another version": (set_in(["research_version"], "metals-research-0.1"), "research_version"),
            "another label": (set_in(["written_by"], "Written by the owner, reviewed."), "written_by"),
            "metals not an object": (set_in(["metals"], []), "metals"),
            "an unknown metal": (set_in(["metals", "unobtainium"], {}), "metals.unobtainium"),
            "an unknown metal field": (set_in(["metals", "copper", "notes"], ["x"]), copper),
            "a metal that is not an object": (set_in(["metals", "cobalt"], []), "metals.cobalt"),
            "another thesis": (set_in(["metals", "copper", "thesis"], "lithium"), copper + ".thesis"),
            "a passage of another thesis": (set_in(["metals", "copper", "uses"], ["lithium:usgs26-end-uses"]),
                                            copper + ".uses[0]"),
            "a passage named twice": (set_in(["metals", "copper", "recycling"],
                                             ["copper:usgs26-recycling", "copper:usgs26-recycling"]),
                                      copper + ".recycling[1]"),
            "an empty list": (set_in(["metals", "copper", "substitution"], []), copper + ".substitution"),
            "an event with an extra field": (set_in(["metals", "copper", "events", 0, "date"], "2025-01-01"),
                                             copper + ".events[0]"),
            "a short event kind": (set_in(["metals", "copper", "events", 0, "kind"], "Event"),
                                   copper + ".events[0].kind"),
            "an event without its date": (delete(["metals", "copper", "events", 0, "when"]), copper + ".events[0]"),
            "an event date without a year": (set_in(["metals", "copper", "events", 1, "when"], "September"),
                                             copper + ".events[1].when"),
            "an event date that is not text": (set_in(["metals", "copper", "events", 0, "when"], 2025),
                                               copper + ".events[0].when"),
            "a long event date": (set_in(["metals", "copper", "events", 0, "when"], "In the year 2025, " + "x" * 30),
                                  copper + ".events[0].when"),
            "a chain without assumed": (delete(chain0 + ["assumed"]), cc),
            "a chain with an extra field": (set_in(chain0 + ["sources"], []), cc),
            "a chain id that is not a slug": (set_in(chain0 + ["id"], "Copper Grid"), cc + ".id"),
            "a chain id used twice": (set_in(["metals", "cobalt", "chains", 0, "id"], "copper-grid-construction"),
                                      "metals.cobalt.chains[0].id"),
            "an unknown link kind": (link(0, {"text": "Synthetic link text", "kind": "guess"}), cc + ".links[0].kind"),
            "a link kind that is a list": (link(0, {"text": "Synthetic link text", "kind": ["measured"]}),
                                           cc + ".links[0].kind"),
            "a measured link with a passage": (link(0, {"text": "Synthetic link text", "kind": "measured",
                                                        "passage": "copper:usgs26-end-uses"}), cc + ".links[0]"),
            "a stated link with a ref": (link(2, {"text": "Synthetic link text", "kind": "stated",
                                                  "ref": {"reliance": "2025"}}), cc + ".links[2]"),
            "a hypothesis with a passage": (link(6, {"text": "Synthetic link text", "kind": "hypothesis",
                                                     "passage": "copper:usgs26-end-uses"}), cc + ".links[6]"),
            "a ref of no known shape": (link(0, measured({"stage": "mining"})), cc + ".links[0].ref"),
            "a ref that is not an object": (link(0, measured("mining")), cc + ".links[0].ref"),
            "an unknown stage": (link(0, measured({"stage": "smelting", "figure": "leader"})),
                                 cc + ".links[0].ref.stage"),
            "an unknown figure": (link(0, measured({"stage": "mining", "figure": "cr2"})), cc + ".links[0].ref.figure"),
            "years of mining": (link(0, measured({"stage": "mining", "figure": "years"})), cc + ".links[0].ref.figure"),
            "years of refining": (link(0, measured({"stage": "refining", "figure": "years"})),
                                  cc + ".links[0].ref.figure"),
            "another reliance year": (link(0, measured({"reliance": "2024"})), cc + ".links[0].ref.reliance"),
            "an IEA name of another metal": (link(0, measured({"iea": "Lithium", "technology": "Electric vehicles"})),
                                             cc + ".links[0].ref.iea"),
            "an IEA name not mapped": (link(0, measured({"iea": "Unobtainium", "technology": "Wind"})),
                                       cc + ".links[0].ref.iea"),
            "an empty technology": (link(0, measured({"iea": "Copper", "technology": ""})),
                                    cc + ".links[0].ref.technology"),
            "another direction": (set_in(chain0 + ["gains_losses", 0, "direction"], "will gain"),
                                  cc + ".gains_losses[0].direction"),
            "a short text": (set_in(chain0 + ["links", 0, "text"], "Short"), cc + ".links[0].text"),
            "a long text": (set_in(chain0 + ["title"], "x" * 401), cc + ".title"),
            "text over two lines": (set_in(chain0 + ["disruption"], "Output falls\nat mines."), cc + ".disruption"),
            "markup": (set_in(chain0 + ["disruption"], "Output <b>falls</b> at mines."), cc + ".disruption"),
            "a leading space": (set_in(chain0 + ["learned"], " Measured here: shares."), cc + ".learned"),
            "a number for text": (set_in(chain0 + ["assumed"], 12345678), cc + ".assumed"),
            "an empty direct list": (set_in(chain0 + ["direct"], []), cc + ".direct"),
            "an empty mitigant": (set_in(chain0 + ["mitigants", 1], ""), cc + ".mitigants[1]"),
            "a mitigant with markup": (set_in(chain0 + ["indirect", 0], "**Builders**"), cc + ".indirect[0]"),
            "a long mitigant": (set_in(chain0 + ["direct", 2], "x" * 401), cc + ".direct[2]"),
            "no links": (set_in(chain0 + ["links"], []), cc + ".links"),
        }
        for name, (change, place) in cases.items():
            with self.subTest(name):
                self.refused(change, place)

    def test_a_passage_the_thesis_does_not_hold_refuses(self):
        held = {name: evidence(name) for name in REAL_PASSAGES if name != "usgs26-end-uses"}
        with self.assertRaises(ResearchRefused) as raised:
            self.resolve(real(), held)
        self.assertEqual(raised.exception.place, "metals.copper.uses[0]")

    def test_resolve_changes_nothing_it_is_given(self):
        body = real()
        passages = real_passages(body)
        before = json.dumps([body, passages, self.chapters, self.risk, self.uses], sort_keys=True)
        self.resolve(body, passages)
        self.assertEqual(json.dumps([body, passages, self.chapters, self.risk, self.uses], sort_keys=True), before)


class ResolveTests(Inputs):
    def link(self, metal, ref, **withheld):
        """(shown, unavailable) of one measured link on ``metal``."""
        resolved = self.resolve(content({metal: {"chains": [chain([measured(ref)])]}}), **withheld)
        got = resolved["metals"][metal]["chains"][0]["links"][0]
        self.assertEqual(set(got), {"text", "kind", "ref", "shown", "unavailable"})
        self.assertEqual(got["ref"], ref)
        return got["shown"], got["unavailable"]

    def shown(self, metal, ref, expected, **withheld):
        self.assertEqual(self.link(metal, ref, **withheld), (expected, None))

    def unavailable(self, metal, ref, reason, **withheld):
        self.assertEqual(self.link(metal, ref, **withheld), (None, reason))

    def test_leaders_by_stage(self):
        self.shown("copper", {"stage": "mining", "figure": "leader"}, "Chile 23.0%")
        self.shown("copper", {"stage": "refining", "figure": "leader"}, "China 44.4%")
        self.shown("copper", {"stage": "reserves", "figure": "leader"}, "Chile 19.4%")

    def test_top_three(self):
        self.shown("cobalt", {"stage": "mining", "figure": "top3"},
                   "88.5% (Congo (Kinshasa), Indonesia, United States)")
        self.unavailable("copper", {"stage": "mining", "figure": "top3"}, "Fewer than three countries are named")

    def test_hhi_bounds_grouped_and_one_number_when_equal(self):
        self.shown("cobalt", {"stage": "mining", "figure": "hhi"}, "5,706–5,839")
        self.shown("copper", {"stage": "refining", "figure": "hhi"}, "2,030–4,348")
        self.shown("manganese", {"stage": "mining", "figure": "hhi"}, "6,100")
        self.unavailable("rare-earths", {"stage": "mining", "figure": "hhi"},
                         "The world total is printed as “>2,000,000”, not as a number")

    def test_a_withheld_order_gives_its_reason(self):
        self.unavailable("nickel", {"stage": "mining", "figure": "leader"},
                         "United States is printed as “W”, so the order is unknown")
        self.unavailable("rare-earths", {"stage": "mining", "figure": "leader"},
                         "The world total is printed as “>2,000,000”, not as a number")

    def test_a_missing_stage_reads_as_missing(self):
        self.unavailable("cobalt", {"stage": "refining", "figure": "leader"},
                         "USGS prints no 2025 production series at the refining stage for this metal")
        self.unavailable("gallium", {"stage": "mining", "figure": "hhi"},  # Its only stage is "other".
                         "USGS prints no 2025 production series at the mining stage for this metal")

    def test_reserves_and_years(self):
        self.shown("copper", {"stage": "reserves", "figure": "years"}, "43 years")
        self.shown("copper", {"stage": "reserves", "figure": "hhi"}, "526–5,200")
        self.shown("silver", {"stage": "reserves", "figure": "years"}, "less than 1 year")
        self.shown("manganese", {"stage": "reserves", "figure": "years"}, "1 year")
        vanadium = next(item for item in self.chapters if item["id"] == "vanadium")["years_of_reserves"][0]
        self.assertIsNone(vanadium["shown"])
        self.unavailable("vanadium", {"stage": "reserves", "figure": "years"}, vanadium["reason"])
        self.assertTrue(vanadium["reason"].startswith("Reserves: Unit in doubt"))

    def test_reserves_without_a_pair(self):
        # Iron ore: production and reserves are on different bases, so no pair; its only 2025 reserves series is used.
        self.shown("iron-ore", {"stage": "reserves", "figure": "leader"}, "Australia 30.5%")
        self.unavailable("iron-ore", {"stage": "reserves", "figure": "years"}, "No years figure for this pair")
        for metal in ("gallium", "zinc"):  # No reserves series; two reserves series and no pair.
            for figure in ("leader", "top3", "hhi", "years"):
                self.unavailable(metal, {"stage": "reserves", "figure": figure}, "No matching 2025 reserves series")

    def test_reliance_as_printed(self):
        self.shown("copper", {"reliance": "2025"}, "57%")
        self.shown("rare-earths", {"reliance": "2025"}, ">95")
        self.unavailable("cobalt", {"reliance": "2025"}, "USGS prints no 2025 net import reliance for this metal")

    def test_iea_technology_shares(self):
        self.shown("copper", {"iea": "Copper", "technology": "Wind"}, "10.0% of 2025 energy-technology demand (100 kt of 1000 kt)")
        self.shown("lithium", {"iea": "Lithium", "technology": "Electric vehicles"},
                   "75.0% of 2025 energy-technology demand (150 kt of 200 kt)")
        self.unavailable("copper", {"iea": "Copper", "technology": "Electricity networks"},
                         "The IEA lists no Electricity networks use for Copper in this table")
        # No 3.1 block: technologies null, so the table gives no split at all (not a split without that use).
        self.unavailable("cadmium", {"iea": "Cadmium", "technology": "Wind"},
                         "The IEA's table gives no technology split for Cadmium")
        self.unavailable("cobalt", {"iea": "Cobalt", "technology": "Electric vehicles"},  # No 3.2 row.
                         "The IEA lists no Electric vehicles use for Cobalt in this table")
        self.unavailable("rare-earths", {"iea": "Neodymium", "technology": "Wind"},
                         "The IEA's 2025 energy-technology total for Neodymium is not positive, so no share is "
                         "computed")

    def test_a_withheld_iea_part(self):
        self.uses = None
        problem = "The layout differs at 3.1 Energy demand by tech!A2: expected 'x'"
        self.unavailable("copper", {"iea": "Copper", "technology": "Wind"}, "The IEA part is withheld: " + problem,
                         uses_problem=problem)
        self.shown("copper", {"stage": "mining", "figure": "leader"}, "Chile 23.0%", uses_problem=problem)

    def test_a_withheld_usgs_part(self):
        self.chapters = self.risk = None
        problem = "The retained file's size differs from its acquisition record; it is not read."
        for ref in ({"stage": "mining", "figure": "leader"}, {"stage": "reserves", "figure": "years"},
                    {"reliance": "2025"}):
            self.unavailable("copper", ref, "The USGS part is withheld: " + problem, usgs_problem=problem)
        self.shown("copper", {"iea": "Copper", "technology": "Wind"},
                   "10.0% of 2025 energy-technology demand (100 kt of 1000 kt)", usgs_problem=problem)

    def test_stated_links_and_cited_passages(self):
        stated = {"text": "Synthetic stated link", "kind": "stated", "passage": "copper:usgs26-end-uses"}
        hypothesis = {"text": "Synthetic hypothesis link.", "kind": "hypothesis"}
        body = content({"copper": {"thesis": "copper", "uses": ["copper:usgs26-end-uses"],
                                   "substitution": ["copper:usgs26-substitutes"],
                                   "events": [{"passage": "copper:usgs26-mine-events", "kind": "Supply disruption",
                                               "when": "2025"}],
                                   "chains": [chain([stated, hypothesis,
                                                     {**stated, "passage": "copper:usgs26-mine-events"}])]}})
        passages = {"usgs26-end-uses": evidence("usgs26-end-uses"),
                    "usgs26-substitutes": evidence("usgs26-substitutes", "changed"),
                    "usgs26-mine-events": evidence("usgs26-mine-events", "not_found")}
        got = self.resolve(body, passages)
        self.assertEqual(set(got), {"written_by", "metals"})
        self.assertEqual(got["written_by"], WRITTEN_BY)
        copper = got["metals"]["copper"]
        self.assertEqual(copper["thesis"], "copper")
        self.assertEqual(copper["uses"],
                         [{"passage": "copper:usgs26-end-uses", "evidence": passages["usgs26-end-uses"]}])
        self.assertEqual(copper["substitution"][0]["evidence"]["quote"], None)
        self.assertEqual(copper["substitution"][0]["evidence"]["state"], "changed")
        self.assertEqual(copper["recycling"], [])
        self.assertEqual(copper["events"], [{"kind": "Supply disruption", "when": "2025",
                                             "passage": "copper:usgs26-mine-events",
                                             "evidence": passages["usgs26-mine-events"]}])
        links = copper["chains"][0]["links"]
        self.assertEqual(links[0], {**stated, "evidence": passages["usgs26-end-uses"], "unavailable": None})
        self.assertEqual(links[1], hypothesis)
        self.assertEqual(links[2]["evidence"]["quote"], None)  # Not found where cited: the link is withheld.
        self.assertEqual(links[2]["unavailable"], passages["usgs26-mine-events"]["problem"])
        self.assertEqual({key: value for key, value in copper["chains"][0].items() if key != "links"},
                         {key: value for key, value in chain([]).items() if key != "links"})

    def event(self, when, state="verified"):
        """The one event of a copper note citing usgs26-mine-events in ``state``, resolved."""
        body = content({"copper": {"events": [{"passage": "copper:usgs26-mine-events", "kind": "Supply disruption",
                                               "when": when}]}})
        passages = {"usgs26-mine-events": evidence("usgs26-mine-events", state)}
        return self.resolve(body, passages)["metals"]["copper"]["events"][0]

    def test_an_event_carries_the_date_its_quote_gives(self):
        for when in ("2025", "September 2025"):
            self.assertEqual(self.event(when)["when"], when)

    def test_an_event_date_not_in_its_verified_quote_refuses(self):
        for when in ("March 2025", "2024", "september 2025"):  # Exactly as quoted, case included.
            with self.subTest(when), self.assertRaises(ResearchRefused) as raised:
                self.event(when)
            self.assertEqual(raised.exception.place, "metals.copper.events[0].when")

    def test_an_unverified_event_keeps_its_date_unchecked(self):
        # No quote to check it against; the page lists such an event apart, with no kind or date.
        got = self.event("March 2024", "changed")
        self.assertEqual((got["when"], got["evidence"]["quote"]), ("March 2024", None))

    def test_every_metal_has_every_part(self):
        got = self.resolve(content({"tin": {"chains": [chain([{"text": "Synthetic hypothesis link.",
                                                                "kind": "hypothesis"}])]}}))
        self.assertEqual(got["metals"]["tin"]["thesis"], None)
        for part in ("uses", "substitution", "recycling", "events"):
            self.assertEqual(got["metals"]["tin"][part], [])
        self.assertEqual(len(got["metals"]["tin"]["chains"]), 1)


FCX_EVENT = {"passage": "fcx:q3-p-bagdad-approval", "kind": "Investment decision", "when": "November 2026"}


class FcxEventTests(Inputs):
    def fcx(self, variant="verified", event=None):
        with tempfile.TemporaryDirectory() as tmp:
            research, documents = fcx_fakes.synthetic_package(Path(tmp), variant)
            found = metals_view.fcx_passages(["q3-p-bagdad-approval"], research, documents)
        body = content({"copper": {"events": [event or FCX_EVENT]}})
        return self.resolve(body, {"fcx:" + name: item for name, item in found.items()})["metals"]["copper"]["events"][0]

    def test_register_event_may_cite_an_fcx_passage(self):
        event = self.fcx()
        self.assertEqual(event["evidence"]["state"], "verified")
        self.assertEqual(event["passage"], "fcx:q3-p-bagdad-approval")
        self.assertEqual(event["evidence"]["where"], "page 23")
        self.assertEqual(event["evidence"]["edition"], "10-Q")
        self.assertIn("November 2026", event["evidence"]["quote"])

    def test_fcx_event_is_withheld_when_its_document_changed(self):
        for variant, state in (("10q-changed", "changed"), ("10q-missing", "missing")):
            with self.subTest(variant):
                event = self.fcx(variant)
                self.assertEqual(event["evidence"]["state"], state)
                self.assertIsNone(event["evidence"]["quote"])
                self.assertTrue(event["evidence"]["problem"])

    def test_an_fcx_event_date_must_be_in_its_verified_quote(self):
        with self.assertRaises(ResearchRefused) as raised:
            self.fcx(event={**FCX_EVENT, "when": "March 2026"})
        self.assertEqual(raised.exception.place, "metals.copper.events[0].when")

    def test_an_unreadable_fcx_package_makes_its_passages_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = metals_view.fcx_passages(["q3-p-bagdad-approval"], Path(tmp), Path(tmp))
        self.assertEqual(found["q3-p-bagdad-approval"]["state"], "unavailable")
        self.assertEqual(found["q3-p-bagdad-approval"]["problem"], "The FCX research cannot be read on this machine")

    def test_stated_link_may_not_cite_fcx(self):
        stated = {"text": "Synthetic stated link", "kind": "stated", "passage": "fcx:q3-p-bagdad-approval"}
        body = content({"copper": {"chains": [chain([stated])]}})
        with self.assertRaises(ResearchRefused) as raised:
            metals_research.validate(body)
        self.assertEqual(raised.exception.place, "metals.copper.chains[0].links[0].passage")

    def test_a_list_may_not_cite_fcx(self):
        with self.assertRaises(ResearchRefused):
            metals_research.validate(content({"copper": {"uses": ["fcx:q3-p-bagdad-approval"]}}))

    def test_refs_are_full_and_first_cited_first(self):
        body = content({"copper": {"uses": ["copper:a"], "events": [
            {**FCX_EVENT, "passage": "fcx:a"}, {**FCX_EVENT, "passage": "copper:b"}]}})
        self.assertEqual(metals_research.passage_refs(body), ["copper:a", "fcx:a", "copper:b"])
        self.assertEqual(metals_research.passage_ids(body), ["a", "b"])

    def test_the_view_asks_the_fcx_research_for_fcx_events_only(self):
        body = content({"copper": {"events": [FCX_EVENT]}})
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "metals"
            folder.mkdir()
            (folder / metals_research.FILE).write_bytes(json.dumps(body).encode("utf-8"))
            research, documents = fcx_fakes.synthetic_package(Path(tmp) / "fcx")
            for place, state in ((research, "verified"), (Path(tmp) / "none", "unavailable")):
                got = metals_view._research(folder, None, None, None, "p", "p", Path(tmp) / "theses", Path(tmp),
                                            place, documents)
                self.assertEqual(got["metals"]["copper"]["events"][0]["evidence"]["state"], state)


if __name__ == "__main__":
    unittest.main()
