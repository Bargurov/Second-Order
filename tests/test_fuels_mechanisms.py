import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from second_order import fuels_mechanisms as fm
from second_order.fuels_mechanisms import check_text, load_drivers, load_transmission
from second_order.fuels_sources import CONTENT_DIR, FuelsRefused

SOURCE = {"title": "Report 2026", "publisher": "Agency", "date": "2026-10-01", "url": "https://example.org/r",
          "checked_on": "2026-11-05", "locator": "section 2"}
TOP = {"mechanisms_version": "fuels-mechanisms-0.1", "prepared_on": "2026-11-06", "author": "Claude (AI-drafted)",
       "review": {"state": "unreviewed", "reviewed_on": None}}


def driver(item_id):
    return {"id": item_id, "title": "Title", "mechanism": "Supply can tighten when producers hold output back.",
            "acts_on": "both", "direction": ["Prices tend to firm when supply tightens."],
            "changes_when": ["Demand weakens."], "watch": ["A monthly agency report"], "sources": [dict(SOURCE)]}


def transmission_item(item_id):
    return {"id": item_id, "sector": "Sector", "trigger": "Jet fuel price", "chain": ["Fuel", "Costs", "Fares"],
            "effect": "negative", "effect_text": "Margins can narrow if costs are not passed on.",
            "second_order": ["Capacity can be cut."], "flips_when": ["Hedges are in place."],
            "lag": "Weeks to months, depending on contracts.", "lag_sourced": False, "sources": []}


def drivers(**over):
    base = dict(TOP, kind="drivers", items=[driver(i) for i in fm.DRIVER_IDS])
    base.update(over)
    return base


def transmission(**over):
    base = dict(TOP, kind="transmission", items=[transmission_item(i) for i in fm.SECTOR_IDS])
    base.update(over)
    return base


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, name, data):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        (self.dir / name).write_bytes(raw)

    def refused(self, loader, name, data, *needles):
        self.write(name, data)
        with self.assertRaises(FuelsRefused) as caught:
            loader(self.dir)
        self.assertEqual(caught.exception.status, 500)
        for needle in needles:
            self.assertIn(needle, str(caught.exception))
        return str(caught.exception)


class Loading(Case):
    def test_valid_files_load(self):
        self.write("drivers.json", drivers())
        self.write("transmission.json", transmission())
        self.assertEqual(load_drivers(self.dir)["kind"], "drivers")
        self.assertEqual(len(load_transmission(self.dir)["items"]), 7)

    def test_absent_files_are_none(self):
        self.assertIsNone(load_drivers(self.dir))
        self.assertIsNone(load_transmission(self.dir))

    def test_reviewed_state(self):
        self.write("drivers.json", drivers(review={"state": "reviewed", "reviewed_on": "2026-11-07"}))
        self.assertEqual(load_drivers(self.dir)["review"]["state"], "reviewed")
        self.refused(load_drivers, "drivers.json", drivers(review={"state": "reviewed", "reviewed_on": "2026-11-01"}),
                     "review.reviewed_on")
        self.refused(load_drivers, "drivers.json",
                     drivers(review={"state": "unreviewed", "reviewed_on": "2026-11-07"}), "review.reviewed_on")

    def test_year_and_crack_token_pass(self):
        self.assertEqual(check_text("In 2026 the 3-2-1 spread", "w", 100), "In 2026 the 3-2-1 spread")

    def test_phrases_are_word_bounded(self):
        for text in ("Market expectations", "Because it rains", "Unexpected news", "The forecasting office"):
            self.assertEqual(check_text(text, "w", 100), text)


class Refusals(Case):
    def test_text_rules(self):
        for text in ("Output of 5 units", "The 5th", "In 20266", "3-2-2 spread", "1999x"):
            with self.subTest(text):
                data = drivers()
                data["items"][0]["mechanism"] = text
                message = self.refused(load_drivers, "drivers.json", data, "drivers.json", "opec_supply", "mechanism")
                self.assertNotIn(text, message)

    def test_each_refused_phrase(self):
        for phrase in ("caused", "causes", "drove", "driven by", "due to", "because of", "as a result of", "led to",
                       "triggered", "will rise", "will fall", "will increase", "will decrease", "forecast",
                       "expect", "expects", "expected"):
            for text in (f"It {phrase} a change", f"It {phrase.upper()} a change",
                         f"It {phrase.replace(' ', chr(10))} a change"):
                with self.subTest(text):
                    data = transmission()
                    data["items"][2]["effect_text"] = text
                    message = self.refused(load_transmission, "transmission.json", data, "transmission.json",
                                           "refiners_energy", "effect_text")
                    self.assertNotIn(text, message)

    def test_mechanism_prose_may_not_point_at_a_time_narrate_a_move_or_forecast(self):
        """General mechanisms must never read as the explanation of the current move (rule 1): beyond the shared
        phrase rule, no time reference, no past-tense account of a price move and no forecast wording."""
        for text in ("Recent OPEC+ cuts have lifted Brent this week.", "The crack widened on the back of outages.",
                     "Prices rose because refiners cut runs.", "Gasoline stocks drive the current move.",
                     "Outages which will push the crack wider.", "The spread is likely to keep widening.",
                     "Output is currently low.", "Stocks are tight now.", "Amid outages, margins can firm.",
                     "So far this year, demand can firm.", "The latest cut can tighten supply.",
                     "Thanks to strong demand, prices can firm.", "Owing to outages, margins can firm.",
                     "Strikes resulted in lower runs.", "Demand drives the crack.", "Cuts are set to tighten supply.",
                     "Stocks fell.", "Brent soared.", "Last month demand could firm.", "Lately, demand can firm."):
            with self.subTest(text):
                data = drivers()
                data["items"][3]["mechanism"] = text
                message = self.refused(load_drivers, "drivers.json", data, "refining", "mechanism")
                self.assertNotIn(text, message)

    def test_general_present_tense_prose_and_publication_names_still_pass(self):
        for text in ("Strong driving demand tends to support gasoline prices.", "Households can drive less.",
                     "Because yields are only partly flexible, a shortfall can widen one crack.",
                     "Prices can sit above what current supply and demand alone would support.",
                     "EIA This Week in Petroleum", "A better growth outlook can lift futures prices."):
            with self.subTest(text):
                self.assertEqual(check_text(text, "here", 600), text)
        # The situation note describes the current prices by design, so it keeps the shared rule only.
        self.assertFalse(fm.refused_phrase("Brent rose this week"))

    def test_phrase_in_source_publisher_and_list_entry(self):
        data = drivers()
        data["items"][1]["sources"][0]["publisher"] = "The agency that drove prices"
        self.refused(load_drivers, "drivers.json", data, "global_demand", "sources[0].publisher")
        data = drivers()
        data["items"][1]["watch"][0] = "Forecast release"
        self.refused(load_drivers, "drivers.json", data, "global_demand", "watch[0]")

    def test_source_title_and_locator_quote_verbatim(self):
        # Ruling S6: a source's own title and locator are quoted as published, so the refused phrases do not apply.
        data = drivers()
        data["items"][6]["sources"][0]["title"] = ("The changing nexus between commodity prices and the dollar: causes "
                                                   "and implications")
        data["items"][6]["sources"][0]["locator"] = "What drove prices, and what is expected"
        self.write("drivers.json", data)
        self.assertIn("causes", load_drivers(self.dir)["items"][6]["sources"][0]["title"])
        data["items"][6]["mechanism"] = "A stronger dollar causes lower demand."
        self.refused(load_drivers, "drivers.json", data, "dollar_rates_growth", "mechanism")

    def test_source_title_may_hold_digits(self):
        data = drivers()
        data["items"][0]["sources"][0]["title"] = "Annual Energy Outlook 2026, table 12"
        data["items"][0]["sources"][0]["locator"] = None
        self.write("drivers.json", data)
        load_drivers(self.dir)

    def test_missing_and_extra_fields(self):
        data = drivers()
        del data["items"][3]["watch"]
        self.refused(load_drivers, "drivers.json", data, "refining")
        data = drivers()
        data["items"][3]["extra"] = "x"
        self.refused(load_drivers, "drivers.json", data, "refining")
        data = drivers()
        data["note"] = "x"
        self.refused(load_drivers, "drivers.json", data, "drivers.json")
        data = drivers()
        data["items"][0]["sources"][0]["extra"] = 1
        self.refused(load_drivers, "drivers.json", data, "opec_supply", "sources[0]")

    def test_ids_order_missing_extra(self):
        data = drivers()
        data["items"].reverse()
        self.refused(load_drivers, "drivers.json", data, "items")
        data = drivers()
        del data["items"][-1]
        self.refused(load_drivers, "drivers.json", data, "items")
        data = drivers()
        data["items"].append(driver("seasonality"))
        self.refused(load_drivers, "drivers.json", data, "items")

    def test_kind_version_author(self):
        self.refused(load_drivers, "drivers.json", drivers(kind="transmission"), "kind")
        self.refused(load_drivers, "drivers.json", drivers(mechanisms_version="x"), "mechanisms_version")
        self.refused(load_drivers, "drivers.json", drivers(author="Someone"), "author")

    def test_unlisted_acts_on_and_effect(self):
        data = drivers()
        data["items"][0]["acts_on"] = "oil"
        self.refused(load_drivers, "drivers.json", data, "opec_supply", "acts_on")
        data = transmission()
        data["items"][1]["effect"] = "up"
        self.refused(load_transmission, "transmission.json", data, "shipping_logistics", "effect")

    def test_short_chain_and_long_step(self):
        data = transmission()
        data["items"][0]["chain"] = ["Fuel", "Costs"]
        self.refused(load_transmission, "transmission.json", data, "aviation", "chain")
        data = transmission()
        data["items"][0]["chain"][1] = "x" * 61
        self.refused(load_transmission, "transmission.json", data, "aviation", "chain[1]")

    def test_lag_sourced_needs_sources(self):
        data = transmission()
        data["items"][0]["lag_sourced"] = True
        self.refused(load_transmission, "transmission.json", data, "aviation", "lag_sourced")
        data["items"][0]["sources"] = [dict(SOURCE)]
        self.write("transmission.json", data)
        load_transmission(self.dir)
        data["items"][0]["lag_sourced"] = "yes"
        self.refused(load_transmission, "transmission.json", data, "aviation", "lag_sourced")

    def test_source_rules(self):
        for field, value in (("url", "http://example.org/r"), ("checked_on", "2026-11-07"),
                             ("date", "2026-13-01"), ("checked_on", None)):
            with self.subTest(field, value=value):
                data = drivers()
                data["items"][0]["sources"][0][field] = value
                self.refused(load_drivers, "drivers.json", data, "opec_supply", f"sources[0].{field}")

    def test_lengths(self):
        data = drivers()
        data["items"][0]["title"] = "x" * 81
        self.refused(load_drivers, "drivers.json", data, "title")
        data = drivers()
        data["items"][0]["mechanism"] = "x" * 601
        self.refused(load_drivers, "drivers.json", data, "mechanism")
        data = drivers()
        data["items"][0]["direction"] = []
        self.refused(load_drivers, "drivers.json", data, "direction")

    def test_at_most_ten_sources(self):
        data = drivers()
        data["items"][0]["sources"] = [dict(SOURCE) for _ in range(10)]
        self.write("drivers.json", data)
        self.assertEqual(len(load_drivers(self.dir)["items"][0]["sources"]), 10)
        data["items"][0]["sources"].append(dict(SOURCE))
        self.refused(load_drivers, "drivers.json", data, "opec_supply", "sources")

    def test_at_most_twenty_entries(self):
        data = drivers()
        data["items"][0]["direction"] = ["Prices tend to firm when supply tightens."] * 20
        self.write("drivers.json", data)
        self.assertEqual(len(load_drivers(self.dir)["items"][0]["direction"]), 20)
        data["items"][0]["direction"].append("Prices tend to firm when supply tightens.")
        self.refused(load_drivers, "drivers.json", data, "opec_supply", "direction")
        data = transmission()
        data["items"][0]["chain"] = ["Step"] * 21
        self.refused(load_transmission, "transmission.json", data, "aviation", "chain")

    def test_source_texts_at_most_two_hundred_characters(self):
        for field in ("title", "publisher", "locator"):
            with self.subTest(field):
                data = drivers()
                data["items"][0]["sources"][0][field] = "x" * 200
                self.write("drivers.json", data)
                load_drivers(self.dir)
                data["items"][0]["sources"][0][field] = "x" * 201
                self.refused(load_drivers, "drivers.json", data, "opec_supply", f"sources[0].{field}")

    def test_a_file_over_two_hundred_thousand_bytes_is_refused(self):
        raw = json.dumps(drivers()).encode()
        padded = raw[:1] + b" " * (fm.MAX_FILE_BYTES - len(raw)) + raw[1:]
        self.assertEqual((len(padded), fm.MAX_FILE_BYTES), (200_000, 200_000))
        self.write("drivers.json", padded)
        self.assertEqual(load_drivers(self.dir)["kind"], "drivers")
        message = self.refused(load_drivers, "drivers.json", raw[:1] + b" " + padded[1:], "drivers.json")
        self.assertIn("larger than the limit", message)

    def test_a_phrase_split_by_a_non_breaking_space_is_refused(self):
        data = transmission()
        data["items"][2]["effect_text"] = "Margins narrowed due to outages."
        self.refused(load_transmission, "transmission.json", data, "refiners_energy", "effect_text")

    def test_the_crack_token_must_stand_alone(self):
        for text in ("The 3-2-10 spread", "A 13-2-1 mix", "The 3-2-1-1 basket"):
            with self.subTest(text):
                data = drivers()
                data["items"][3]["mechanism"] = text
                message = self.refused(load_drivers, "drivers.json", data, "refining", "mechanism", "numbers")
                self.assertNotIn(text, message)

    def test_bad_bytes_and_duplicate_keys(self):
        self.refused(load_drivers, "drivers.json", b"\xff\xfe{}", "drivers.json")
        good = json.dumps(drivers())
        self.refused(load_drivers, "drivers.json", good[:-1].encode() + b', "kind": "drivers"}', "drivers.json")

    def test_non_string_entries_do_not_escape(self):
        for value in (5, None, {"a": 1}, ["x"], True):
            with self.subTest(value=value):
                data = drivers()
                data["items"][0]["direction"][0] = copy.deepcopy(value)
                self.refused(load_drivers, "drivers.json", data, "opec_supply", "direction[0]")
        for value in (5, None, ["x"]):
            with self.subTest(top=value):
                self.refused(load_drivers, "drivers.json", drivers(items=value), "items")
        self.refused(load_drivers, "drivers.json", [1], "drivers.json")


PAGE_CHECK_FILE = Path(__file__).resolve().parent.parent / "frontend" / "tests" / "browser" / "fuels-check.mjs"


def read_page_check_patterns(source):
    """The regular expressions in the AFFIRMATIVE list of the Stage 1 page check (fuels-check.mjs, which scans every
    page load), read from its source so the two never drift. Each is a flagless /.../ literal; a "/" inside a character
    class or after a backslash does not end it. Fails loudly when the list is not found or holds no pattern."""
    head = re.search(r"const AFFIRMATIVE = \[(.*?)\n\];", source, re.DOTALL)
    if head is None:
        raise AssertionError("fuels-check.mjs has no AFFIRMATIVE list")
    body, patterns, index = head.group(1), [], 0
    while index < len(body):
        if body[index] != "/":
            index += 1
            continue
        index, chars, in_class = index + 1, [], False
        while body[index] != "/" or in_class:
            if body[index] == "\\":
                chars.append(body[index:index + 2])
                index += 2
                continue
            in_class = (in_class or body[index] == "[") and body[index] != "]"
            chars.append(body[index])
            index += 1
        patterns.append(re.compile("".join(chars)))
        index += 1
    if not patterns:
        raise AssertionError("the AFFIRMATIVE list of fuels-check.mjs holds no pattern")
    return patterns


PAGE_CHECK_PATTERNS = read_page_check_patterns(PAGE_CHECK_FILE.read_text(encoding="utf-8"))


def page_check_hits(text):
    """The page check's patterns that match text, lower-cased with whitespace collapsed as the page check does."""
    lowered = re.sub(r"\s+", " ", text.lower())
    return [pattern.pattern for pattern in PAGE_CHECK_PATTERNS if pattern.search(lowered)]


def page_check_findings(items, text_fields, list_fields):
    """(item id, field, pattern) for every page-check hit in the named text fields and list fields of the items, and in
    each source's title, publisher and locator, which the page renders too."""
    found = []
    for item in items:
        for name in text_fields:
            found += [(item["id"], name, hit) for hit in page_check_hits(item[name])]
        for name in list_fields:
            for index, entry in enumerate(item[name]):
                found += [(item["id"], f"{name}[{index}]", hit) for hit in page_check_hits(entry)]
        for index, source in enumerate(item["sources"]):
            for name in ("title", "publisher", "locator"):
                if source[name] is not None:
                    found += [(item["id"], f"sources[{index}].{name}", hit) for hit in page_check_hits(source[name])]
    return found


class Committed(unittest.TestCase):
    def test_the_committed_drivers_pass(self):
        data = load_drivers(CONTENT_DIR)
        self.assertIsNotNone(data)
        self.assertEqual((data["author"], data["review"], data["prepared_on"]),
                         ("Claude (AI-drafted)", {"state": "unreviewed", "reviewed_on": None}, "2026-11-06"))
        self.assertEqual([item["id"] for item in data["items"]], list(fm.DRIVER_IDS))
        self.assertEqual({item["id"]: item["acts_on"] for item in data["items"]},
                         {"opec_supply": "crude", "global_demand": "both", "inventories": "both", "refining": "crack",
                          "geopolitics": "both", "shipping": "both", "dollar_rates_growth": "crude",
                          "seasonality": "crack"})

    def test_the_committed_drivers_pass_the_page_phrase_scan(self):
        # Ruling S7: the prose and the rendered source fields must also pass the Stage 1 page check, which scans every
        # page load.
        data = load_drivers(CONTENT_DIR)
        self.assertEqual(page_check_findings(data["items"], ("title", "mechanism"),
                                             ("direction", "changes_when", "watch")), [])

    def test_the_committed_transmission_passes(self):
        data = load_transmission(CONTENT_DIR)
        self.assertIsNotNone(data)
        self.assertEqual((data["author"], data["review"], data["prepared_on"]),
                         ("Claude (AI-drafted)", {"state": "unreviewed", "reviewed_on": None}, "2026-11-06"))
        self.assertEqual([item["id"] for item in data["items"]], list(fm.SECTOR_IDS))
        self.assertEqual({item["id"]: item["effect"] for item in data["items"]},
                         {"aviation": "negative", "shipping_logistics": "mixed", "refiners_energy": "mixed",
                          "chemicals": "mixed", "agriculture": "negative", "consumer_retail": "negative",
                          "inflation_policy": "mixed"})

    def test_the_committed_transmission_passes_the_page_phrase_scan(self):
        # Ruling S7, as for the drivers: the transmission prose and source fields are rendered on the same page.
        data = load_transmission(CONTENT_DIR)
        self.assertEqual(page_check_findings(data["items"], ("sector", "trigger", "effect_text", "lag"),
                                             ("chain", "second_order", "flips_when")), [])

    def test_the_page_phrase_scan_flags_what_the_page_check_flags(self):
        for text in ("Higher prices tend to follow", "Product prices rise", "Brent today", "The upside case",
                     "We recommend buying", "prices are expected to rise", "Upward pressure"):
            with self.subTest(text):
                self.assertTrue(page_check_hits(text))
        self.assertEqual(page_check_hits("Prices tend to firm when stocks are low."), [])

    def test_the_page_check_patterns_are_read_from_the_browser_check(self):
        # M9: read from fuels-check.mjs itself, never copied, so the two lists cannot drift.
        self.assertGreaterEqual(len(PAGE_CHECK_PATTERNS), 20)
        self.assertEqual(PAGE_CHECK_PATTERNS[0].pattern, r"\b(?:we|i) (?:recommend|suggest|advise)\b")
        self.assertEqual(PAGE_CHECK_PATTERNS[-1].pattern, r"\btoday\b")
        parsed = read_page_check_patterns('const AFFIRMATIVE = [\n  /a[/]b\\/c/, /\\bd\\b/,\n];')
        self.assertEqual([pattern.pattern for pattern in parsed], [r"a[/]b\/c", r"\bd\b"])
        for broken in ("const OTHER = [\n  /a/,\n];", "const AFFIRMATIVE = [\n  'a',\n];"):
            with self.subTest(broken):
                with self.assertRaises(AssertionError):
                    read_page_check_patterns(broken)


if __name__ == "__main__":
    unittest.main()
