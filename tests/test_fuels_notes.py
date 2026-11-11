import copy
import json
import re
import tempfile
import unittest
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

import fuels_fakes
from second_order import fuels_crack, fuels_notes, fuels_situation, fuels_sources
from second_order.fuels_notes import check_note, fill, load_notes, placed
from second_order.fuels_sources import FuelsRefused

D1, D2, D3 = date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 9)


def barrel_on(day, brent, gasoline="2.5", diesel="3"):
    return fuels_crack.barrel({"brent": {day: Fraction(brent)}, "gasoline": {day: Fraction(gasoline)},
                               "diesel": {day: Fraction(diesel)}})


def two_days(brent_then, brent_now):
    return fuels_crack.barrel({"brent": {D1: Fraction(brent_then), D2: Fraction(brent_now)},
                               "gasoline": {D1: Fraction(3), D2: Fraction(3)},
                               "diesel": {D1: Fraction(3), D2: Fraction(3)}})


def note(**overrides):
    base = {
        "note_version": "fuels-note-0.1", "number": 1, "written_on": "2026-11-10", "covers_through": "2026-11-09",
        "snapshot_id": "a" * 64, "observation_date": "2026-11-02", "author": "Claude (AI-drafted)",
        "review": {"state": "unreviewed", "reviewed_on": None},
        "headline": "Brent spot at {brent}, crack {crack}",
        "lede": "In 2026 Brent spot was {brent}, the basket {basket}, {brent_change}.",
        "columns": {"supply": "Supply text.", "demand": "Demand text.", "stocks": "Stocks text."},
        "sources": [{"title": "Report", "publisher": "Agency", "date": "2026-11-09",
                     "url": "https://example.org/report", "locator": "table 1"}],
    }
    base.update(overrides)
    return base


class NoteTests(unittest.TestCase):
    def test_a_synthetic_note_passes_and_fills_from_its_own_snapshot(self):
        n = check_note(note(), 1)
        b = barrel_on(D1, "80")
        p = placed(n, "a" * 64, b, b)
        self.assertEqual(p["state"], "current")
        self.assertEqual(p["headline"], "Brent spot at $80.00, crack $32.00")
        self.assertIn("the basket $112.00", p["lede"])
        self.assertIn("with no earlier common observation", p["lede"])

    def test_fill_formats(self):
        self.assertEqual(fill("{crack}", barrel_on(D1, "115")), "−$3.00")
        self.assertEqual(fill("{brent_change}", two_days("114.04", "115")), "+$0.96 since 2 Nov 2026")
        self.assertEqual(fill("{brent_change}", two_days("115", "114.04")), "−$0.96 since 2 Nov 2026")
        self.assertEqual(fill("{brent_change}", two_days("80", "80")), "unchanged since 2 Nov 2026")

    def test_digits_in_prose_are_refused_but_years_and_placeholders_are_not(self):
        self.assertRaises(FuelsRefused, check_note, note(lede="Brent rose 3 percent"), 1)
        check_note(note(lede="In 2026 Brent spot was {brent}."), 1)

    def test_refused_phrases_in_the_prose_are_refused_naming_the_field(self):
        # Ruling S12: the mechanisms' refused-phrase rule applies to the note's prose (headline, lede, columns).
        columns = {"supply": "Supply text.", "demand": "Demand text.", "stocks": "Stocks text."}
        cases = [("headline", note(headline="Brent drove the crack")),
                 ("lede", note(lede="EIA's November STEO EXPECTS stocks to build.")),
                 ("lede", note(lede="Stocks fell, driven\nby exports.")),
                 ("columns.supply", note(columns={**columns, "supply": "Output dipped due to maintenance."})),
                 ("columns.demand", note(columns={**columns, "demand": "Demand will rise into winter."})),
                 ("columns.stocks", note(columns={**columns, "stocks": "A draw as a result of exports."}))]
        for field, bad in cases:
            with self.subTest(field=field):
                with self.assertRaises(FuelsRefused) as caught:
                    check_note(bad, 1)
                self.assertEqual(caught.exception.status, 500)
                self.assertIn(f"note 1.{field}", str(caught.exception))
                self.assertIn("phrasing", str(caught.exception))
                self.assertNotIn("STEO", str(caught.exception))
        for fine in ("An unexpected draw, says EIA's November STEO.", "The forecasting office lists stocks."):
            check_note(note(lede=fine), 1)

    def test_the_notes_and_the_mechanisms_share_one_phrase_rule(self):
        from second_order import fuels_mechanisms
        self.assertIs(fuels_mechanisms.REFUSED_PHRASES, fuels_notes.REFUSED_PHRASES)
        self.assertTrue(fuels_notes.refused_phrase("It was Triggered by a strike"))
        self.assertFalse(fuels_notes.refused_phrase("Market expectations"))

    def test_unknown_placeholders_and_stray_braces_are_refused(self):
        for text in ("{wti} is up", "a { b", "b } a", "{{brent}}", "{}"):
            with self.assertRaises(FuelsRefused, msg=text):
                check_note(note(lede=text), 1)

    def test_lengths_and_shape_are_checked(self):
        self.assertRaises(FuelsRefused, check_note, note(headline="x" * 121), 1)
        self.assertRaises(FuelsRefused, check_note, note(lede="x" * 601), 1)
        self.assertRaises(FuelsRefused, check_note,
                          note(columns={"supply": "a", "demand": "b", "stocks": "c" * 201}), 1)
        self.assertRaises(FuelsRefused, check_note, note(extra=1), 1)
        self.assertRaises(FuelsRefused, check_note, note(snapshot_id="A" * 64), 1)
        self.assertRaises(FuelsRefused, check_note, note(author="Someone"), 1)
        self.assertRaises(FuelsRefused, check_note, note(sources=[]), 1)
        bad = note()
        bad["sources"][0]["url"] = "http://example.org"
        self.assertRaises(FuelsRefused, check_note, bad, 1)
        self.assertRaises(FuelsRefused, check_note, note(number=2), 1)

    def test_refusals_name_the_field_not_the_value(self):
        with self.assertRaises(FuelsRefused) as caught:
            check_note(note(lede="secret 77 value"), 1)
        self.assertIn("lede", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(caught.exception.status, 500)

    def test_dates_and_review_are_checked(self):
        self.assertRaises(FuelsRefused, check_note, note(covers_through="2026-11-11"), 1)
        self.assertRaises(FuelsRefused, check_note, note(covers_through="2026-11-08"), 1)
        self.assertRaises(FuelsRefused, check_note, note(observation_date="2026-11-11"), 1)
        self.assertRaises(FuelsRefused, check_note,
                          note(review={"state": "reviewed", "reviewed_on": None}), 1)
        self.assertRaises(FuelsRefused, check_note,
                          note(review={"state": "reviewed", "reviewed_on": "2026-11-09"}), 1)
        self.assertRaises(FuelsRefused, check_note,
                          note(review={"state": "unreviewed", "reviewed_on": "2026-11-10"}), 1)
        check_note(note(review={"state": "reviewed", "reviewed_on": "2026-11-10"}), 1)

    def test_numbers_must_run_from_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            self.assertEqual(load_notes(folder), [])
            (folder / "notes").mkdir()
            (folder / "notes" / "situation-0002.json").write_text(json.dumps(note(number=2)), encoding="utf-8")
            self.assertRaises(FuelsRefused, load_notes, folder)
            (folder / "notes" / "situation-0001.json").write_text(json.dumps(note()), encoding="utf-8")
            self.assertEqual([n["number"] for n in load_notes(folder)], [1, 2])

    def test_the_committed_notes_pass(self):
        """Every committed note checks (none committed is fine too) and needs no snapshot to do so."""
        notes = fuels_notes.load_notes(fuels_sources.CONTENT_DIR)
        self.assertEqual([n["number"] for n in notes], list(range(1, len(notes) + 1)))
        folder = fuels_sources.CONTENT_DIR / fuels_notes.NOTES_DIR
        names = sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []
        self.assertEqual([name for name in names if not re.fullmatch(r"situation-[0-9]{4}\.json", name)], [])

    def test_a_misnamed_situation_file_is_refused_and_other_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "notes"
            folder.mkdir()
            (folder / "situation-0001.json").write_text(json.dumps(note()), encoding="utf-8")
            (folder / "README.md").write_text("not a note", encoding="utf-8")
            self.assertEqual([n["number"] for n in load_notes(Path(tmp))], [1])
            for name in ("situation-2.json", "situation-00002.json", "situation-0002.json.bak",
                         "situation-\u0662\u0660\u0660\u0660.json"):
                with self.subTest(name=name):
                    (folder / name).write_text(json.dumps(note(number=2)), encoding="utf-8")
                    with self.assertRaises(FuelsRefused) as caught:
                        load_notes(Path(tmp))
                    self.assertEqual(caught.exception.status, 500)
                    self.assertIn(name, str(caught.exception))
                    (folder / name).unlink()

    def test_an_invalid_or_duplicate_key_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "notes").mkdir()
            path = Path(tmp) / "notes" / "situation-0001.json"
            path.write_text('{"number": 1, "number": 1}', encoding="utf-8")
            with self.assertRaises(FuelsRefused) as caught:
                load_notes(Path(tmp))
            self.assertEqual(caught.exception.status, 500)

    def test_after_a_refresh_the_note_shows_then_and_now(self):
        n = check_note(note(), 1)
        barrel_positive = barrel_on(D1, "80")
        barrel_negative = barrel_on(D3, "115")
        p = placed(n, "b" * 64, barrel_negative, barrel_positive)
        self.assertEqual((p["state"], p["then"], p["now"]),
                         ("earlier", {"brent": "80.00", "crack": "32.00"}, {"brent": "115.00", "crack": "-3.00"}))
        self.assertIn("$80.00", p["lede"])

    def test_an_earlier_note_says_why_when_the_latest_prices_are_withheld_or_missing(self):
        n = check_note(note(), 1)
        bound = barrel_on(D1, "80")
        withheld = fuels_crack.barrel({"brent": None, "gasoline": None, "diesel": None})
        p = placed(n, "b" * 64, withheld, bound)
        self.assertEqual((p["state"], p["then"], p["now"]), ("earlier", {"brent": "80.00", "crack": "32.00"}, None))
        self.assertIn("withheld", p["problem"])
        self.assertIn("$80.00", p["lede"])
        gone = placed(n, "b" * 64, None, bound)
        self.assertEqual((gone["state"], gone["now"]), ("earlier", None))
        self.assertIn("No latest prices", gone["problem"])

    def test_a_current_note_has_no_then_now_or_problem(self):
        b = barrel_on(D1, "80")
        p = placed(check_note(note(), 1), "a" * 64, b, b)
        self.assertEqual((p["then"], p["now"], p["problem"]), (None, None, None))

    def test_a_note_without_its_snapshot_is_unbound(self):
        n = check_note(note(), 1)
        p = placed(n, "b" * 64, barrel_on(D3, "115"), None)
        self.assertEqual(p["state"], "unbound")
        self.assertTrue(p["problem"])
        self.assertIn("{brent}", p["lede"])
        self.assertIsNone(p["then"])

    def test_a_withheld_bound_barrel_is_unbound(self):
        n = check_note(note(), 1)
        withheld = fuels_crack.barrel({"brent": None, "gasoline": None, "diesel": None})
        self.assertEqual(placed(n, "a" * 64, withheld, withheld)["state"], "unbound")

    def test_a_note_whose_observation_date_differs_is_unbound(self):
        n = check_note(note(), 1)
        b = barrel_on(D2, "80")
        self.assertEqual(placed(n, "a" * 64, b, b)["state"], "unbound")



# ---- fuels-note-0.2: the analysis

def series_inputs(changes: dict, last=date(2026, 11, 3), first=date(2026, 9, 25)) -> dict:
    """Weekday inputs from `first` to `last`: Brent 100, gasoline 2.5, diesel 3, except the values `changes` gives as
    {role: {day: value}}."""
    days = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    days = [day for day in days if day.weekday() < 5]
    base = {"brent": "100", "gasoline": "2.5", "diesel": "3"}
    return {role: {day: Fraction(changes.get(role, {}).get(day, value)) for day in days} for role, value in base.items()}


def bound(inputs: dict) -> tuple:
    return fuels_crack.barrel(inputs), fuels_situation.situation(inputs, {}, date(2026, 11, 6))


WEEK_START, WEEK_END = date(2026, 10, 27), date(2026, 11, 3)


class AnalysisNoteTests(unittest.TestCase):
    def analysis(self, **overrides):
        base = fuels_fakes.analysis_note("a" * 64, "2026-11-03")
        base.update(overrides)
        return base

    def refused(self, change, field):
        n = copy.deepcopy(self.analysis())
        change(n)
        with self.assertRaises(FuelsRefused) as raised:
            check_note(n, 1)
        self.assertIn(field, str(raised.exception))
        return str(raised.exception)

    def test_an_analysis_note_passes_and_fills_every_placeholder_from_its_snapshot(self):
        n = check_note(self.analysis(), 1)
        barrel, situation = bound(series_inputs({"brent": {WEEK_END: "90"}}))
        got = placed(n, "a" * 64, barrel, barrel, situation)
        self.assertEqual(got["state"], "current")
        texts = [got["headline"], got["lede"], *(item["text"] for section in fuels_notes.SECTIONS
                                                  for item in got["analysis"][section]), *got["analysis"]["caveats"]]
        self.assertTrue(all("{" not in text and "}" not in text for text in texts), texts)
        self.assertEqual(got["headline"], "SYNTHETIC: Brent fell over the week while the crack rose")
        self.assertTrue(40 <= fuels_notes.words(got["lede"]) <= 70, fuels_notes.words(got["lede"]))
        self.assertIn("From 27 Oct 2026 to 3 Nov 2026, Brent fell $10.00 a barrel (10.0%) while the crack rose "
                      "$10.00 a barrel, and the product basket was unchanged $0.00 a barrel.", got["lede"])
        self.assertIn("Brent's part and the crack's part moved in opposite directions", got["lede"])

    def test_directions_amounts_and_parts_come_from_the_window(self):
        inputs = series_inputs({"brent": {WEEK_START: "100", WEEK_END: "110"},
                                "gasoline": {WEEK_END: "2.4"}, "diesel": {WEEK_END: "3.2"}})
        barrel, situation = bound(inputs)
        text = fill("{week_brent_move} {week_brent_change} {week_brent_pct}; gasoline {week_gasoline_move} "
                    "{week_gasoline_change}; diesel {week_diesel_move} {week_diesel_change}; parts "
                    "{week_gasoline_part} and {week_diesel_part}; crack {week_crack_move} {week_crack_change}; "
                    "{week_split}", barrel, situation)
        self.assertEqual(text, "rose $10.00 a barrel 10.0%; gasoline fell $0.100 a gallon; diesel rose $0.200 a "
                               "gallon; parts −$2.80 a barrel and +$2.80 a barrel; crack fell $10.00 a barrel; "
                               "Brent's part and the crack's part moved in opposite directions")
        month = fill("{month_from} to {month_to}: Brent {month_brent_move}", barrel, situation)
        self.assertEqual(month, "2 Oct 2026 to 3 Nov 2026: Brent rose")  # 3 Oct is a Saturday

    def test_a_window_the_snapshot_does_not_compute_makes_the_note_unbound(self):
        short = series_inputs({}, first=date(2026, 11, 2))  # two days: no week or month window
        barrel, situation = bound(short)
        got = placed(check_note(self.analysis(), 1), "a" * 64, barrel, barrel, situation)
        self.assertEqual(got["state"], "unbound")
        self.assertIn("does not compute the week window", got["problem"])
        self.assertIn("{week_from}", got["lede"])  # never filled, so the page never shows it as a reading

    def test_without_the_bound_snapshot_an_analysis_is_unbound(self):
        got = placed(check_note(self.analysis(), 1), "b" * 64, None, None, None)
        self.assertEqual((got["state"], got["then"], got["now"]), ("unbound", None, None))

    def test_after_a_refresh_the_analysis_is_earlier_and_still_filled_from_its_own_snapshot(self):
        barrel, situation = bound(series_inputs({"brent": {WEEK_END: "90"}}))
        later = barrel_on(D3, "70")
        got = placed(check_note(self.analysis(), 1), "b" * 64, later, barrel, situation)
        self.assertEqual((got["state"], got["then"]["brent"], got["now"]["brent"]), ("earlier", "90.00", "70.00"))
        self.assertIn("From 27 Oct 2026 to 3 Nov 2026", got["lede"])

    def test_a_first_version_note_is_unchanged_and_cannot_use_the_window_placeholders(self):
        check_note(note(), 1)
        with self.assertRaises(FuelsRefused):
            check_note(note(lede="In 2026 Brent {week_brent_move}."), 1)
        with self.assertRaises(FuelsRefused):
            check_note(note(analysis=self.analysis()["analysis"]), 1)

    def test_analysis_refusals_name_the_field(self):
        A = "note 1.analysis"
        cases = [
            (lambda n: n["analysis"]["meaning"][0].update(kind="guess"), f"{A}.meaning[0].kind"),
            (lambda n: n["analysis"]["meaning"][3].update(sources=[]), f"{A}.meaning[3].sources"),
            (lambda n: n["analysis"]["what_happened"][0].update(sources=[0]), f"{A}.what_happened[0].sources"),
            (lambda n: n["analysis"]["what_happened"][2].update(sources=[1]), f"{A}.what_happened[2].sources"),
            (lambda n: n["analysis"]["meaning"][3].update(sources=[5]), f"{A}.meaning[3].sources"),
            (lambda n: n["analysis"]["meaning"][3].update(sources=[0, 0]), f"{A}.meaning[3].sources"),
            (lambda n: n["analysis"]["relevance"][0].update(mechanism=None), f"{A}.relevance[0].mechanism"),
            (lambda n: n["analysis"]["relevance"][0].update(mechanism="drivers:refining"), f"{A}.relevance[0].mechanism"),
            (lambda n: n["analysis"]["meaning"][2].update(mechanism="transmission:Refiners"), f"{A}.meaning[2].mechanism"),
            (lambda n: n["analysis"]["watch"].pop(), f"{A}.watch"),
            (lambda n: n["analysis"]["watch"].extend([n["analysis"]["watch"][0]] * 2), f"{A}.watch"),
            (lambda n: n["analysis"]["relevance"].append(n["analysis"]["relevance"][0]), f"{A}.relevance"),
            (lambda n: n["analysis"]["meaning"].clear(), f"{A}.meaning"),
            (lambda n: n["analysis"]["meaning"][2].update(text="Diesel rose by twelve or 12 cents."), f"{A}.meaning[2].text"),
            (lambda n: n["analysis"]["meaning"][2].update(text="Analysts expected a wider crack."), f"{A}.meaning[2].text"),
            (lambda n: n["analysis"]["meaning"][2].update(text="The crack {crack_width} widened."), f"{A}.meaning[2].text"),
            (lambda n: n["analysis"]["caveats"].append("A caveat with {brent} in it."), f"{A}.caveats[2]"),
            (lambda n: n["analysis"]["caveats"].clear(), f"{A}.caveats"),
            (lambda n: n["analysis"].update(extra=[]), A),
            (lambda n: n["analysis"]["meaning"][0].pop("mechanism"), f"{A}.meaning[0]"),
            (lambda n: n["sources"].append(dict(n["sources"][0], url="https://example.org/uncited")), "note 1.sources"),
            (lambda n: n.update(lede="Too short {week_split}."), "note 1.lede"),
            (lambda n: n.update(lede=" ".join(["word"] * 71)), "note 1.lede"),
            (lambda n: n.update(columns={"supply": "x", "demand": "y", "stocks": "z"}), "note 1"),
            (lambda n: n.update(note_version="fuels-note-0.3"), "note 1.note_version"),
        ]
        for number, (change, field) in enumerate(cases):
            with self.subTest(number=number, field=field):
                self.refused(change, field)

    def test_a_refusal_names_the_field_not_the_text(self):
        message = self.refused(lambda n: n["analysis"]["meaning"][2].update(text="A secret 42 claim."),
                               "meaning[2].text")
        self.assertNotIn("secret", message)

    def test_the_committed_analysis_is_ai_drafted_unreviewed_and_bound_to_the_real_snapshot(self):
        notes = fuels_notes.load_notes(fuels_sources.CONTENT_DIR)
        n = notes[-1]
        self.assertEqual((n["note_version"], n["author"], n["review"]),
                         ("fuels-note-0.2", "Claude (AI-drafted)", {"state": "unreviewed", "reviewed_on": None}))
        self.assertEqual((n["snapshot_id"], n["observation_date"]),
                         ("9c94687fbae2da835c47fb123a1240120b08be7469d89b586610b9de7147abf7", "2026-11-03"))
        self.assertTrue(all(source["url"].startswith("https://www.eia.gov/") for source in n["sources"]))
        self.assertEqual({item["mechanism"] for item in n["analysis"]["relevance"]},
                         {"transmission:refiners_energy", "transmission:shipping_logistics"})
        self.assertEqual([len(n["analysis"][section]) for section in ("relevance", "watch")], [2, 2])
        kinds = {item["kind"] for section in fuels_notes.SECTIONS for item in n["analysis"][section]}
        self.assertEqual(kinds, set(fuels_notes.KINDS))  # every kind is used, so each is labelled on the page
        barrel, situation = bound(series_inputs({"brent": {WEEK_END: "90"}, "diesel": {WEEK_END: "3.2"}}))
        got = placed(n, n["snapshot_id"], barrel, barrel, situation)
        self.assertEqual(got["state"], "current")
        self.assertTrue(40 <= fuels_notes.words(got["lede"]) <= 70, fuels_notes.words(got["lede"]))
        self.assertIn("not a net margin", got["analysis"]["relevance"][0]["text"])
        self.assertTrue(any("not any refinery's profit" in caveat for caveat in got["analysis"]["caveats"]))


if __name__ == "__main__":
    unittest.main()
