"""GET /api/fuels on SYNTHETIC worlds (tests/fuels_fakes.py) in temporary folders: no real snapshot is read, no key is
set and nothing is requested. The replies the frontend reader is tested against are captured here
(SECOND_ORDER_WRITE_FRONTEND_FIXTURES=1 writes them; otherwise they are compared by parsed JSON)."""
from datetime import date, timedelta
from fractions import Fraction
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import account_fakes
import fuels_fakes
from second_order import fuels_crack, fuels_mechanisms, fuels_notes, fuels_snapshots, fuels_view
from second_order.api import create_app
from second_order.fuels_eia import refresh

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
WRITE_FIXTURES = "SECOND_ORDER_WRITE_FRONTEND_FIXTURES"


def tree(folder: Path) -> dict:
    return {path.relative_to(folder).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in sorted(folder.rglob("*")) if path.is_file()}


class Fuels(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="second-order-fuels-api-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.world = fuels_fakes.write_world(self.root)
        self.content, self.snapshots = self.world["content"], self.world["snapshots"]
        self.accounts = account_fakes.World(self.root / "accounts")

    def client(self, snapshots: Path | None = None, user: str | None = "admin"):
        return self.accounts.client(user, fuels_content=self.content,
                                    fuels_snapshots=snapshots if snapshots is not None else self.snapshots)

    def get(self, **options) -> dict:
        reply = self.client(**options).get("/api/fuels")
        self.assertEqual(reply.status_code, 200, reply.text)
        return reply.json()

    def edit_snapshot(self, mutate):
        path = next(self.snapshots.glob("*.json"))
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def refresh_over(self, data=None, **fake_options):
        shutil.rmtree(self.snapshots)
        fake = fuels_fakes.FakeEia(data or fuels_fakes.datasets(), **fake_options)
        refresh(self.snapshots, self.content, fuels_fakes.FAKE_KEY, None, fake.client(), lambda: fuels_fakes.RETRIEVED)


class Reads(Fuels):
    def assertWithheld(self, v, role):
        row = [s for s in v["series"] if s["role"] == role][0]
        self.assertEqual((row["kind"], row["latest"], row["history"]), ("missing", None, []))

    def test_the_crack_history_covers_the_dates_of_the_three_input_histories(self):
        v = self.get()
        histories = [{d for d, value in s["history"] if value is not None}
                     for s in v["series"] if s["role"] in ("brent", "gasoline", "diesel")]
        self.assertTrue(v["crack_history"])
        for day, _ in v["crack_history"]:
            self.assertTrue(all(day in h for h in histories), day)
        self.assertEqual(v["crack_history"][0][0], max(min(h) for h in histories))

    def test_the_coverage_constant_is_not_mutated(self):
        before = json.dumps(fuels_view.COVERAGE)
        self.get()
        self.assertEqual(json.dumps(fuels_view.COVERAGE), before)
        self.assertEqual(len(fuels_view.COVERAGE), 5)

    def test_a_missing_sources_record_is_503_and_an_invalid_note_is_500(self):
        (self.content / "sources.json").unlink()
        self.assertEqual(self.client().get("/api/fuels").status_code, 503)
        shutil.copyfile(fuels_fakes.fuels_sources.CONTENT_DIR / "sources.json", self.content / "sources.json")
        (self.content / "notes" / "situation-0001.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.client().get("/api/fuels").status_code, 500)

    def test_a_hash_valid_but_malformed_snapshot_is_500_naming_only_the_exception_type(self):
        folder = self.root / "malformed"
        payload = {"snapshot_version": fuels_snapshots.SNAPSHOT_VERSION, "semantics": fuels_snapshots.SEMANTICS,
                   "retrieved_at": "2026-11-06T14:00:00+00:00", "retrieved_on": "2026-11-06", "provider": "eia",
                   "adapter_version": "SYNTHETIC"}  # no "series"
        fuels_snapshots.write(folder, payload)
        self.assertEqual(fuels_snapshots.load_all(folder)["state"], "verified")
        reply = self.client(snapshots=folder).get("/api/fuels")
        self.assertEqual(reply.status_code, 500, reply.text)
        detail = reply.json()["detail"]
        self.assertIn("(KeyError)", detail)
        self.assertNotIn("series", detail)

    def test_the_view_on_the_synthetic_snapshot(self):
        v = self.get()
        b = v["barrel"]
        self.assertEqual(v["view_version"], "fuels-view-0.5")
        self.assertEqual((b["state"], b["basket"]["shown"], b["crack"]["shown"], b["inputs"]["brent"]["shown"]),
                         ("computed", "112.00", "32.00", "80.00"))
        # EIA's API gives no publication date: none is shown, and none is inferred.
        self.assertEqual((b["date"], b["previous_date"], b["published_on"]), ("2026-11-03", "2026-11-02", None))
        self.assertEqual({s["latest"]["published_on"] for s in v["series"]}, {None})
        self.assertEqual(v["note"]["state"], "current")
        self.assertIn("$80.00", v["note"]["lede"])
        self.assertEqual([s["kind"] for s in v["series"]], ["published"] * 5)
        self.assertEqual([s["role"] for s in v["series"]], ["brent", "wti", "gasoline", "diesel", "henry_hub"])
        self.assertTrue(all(s["attribution"].startswith("Source: U.S. Energy Information Administration, ")
                            and "retrieved November 6, 2026" in s["attribution"] for s in v["series"]))
        self.assertEqual([s["series_id"] for s in v["series"]],
                         ["RBRTE", "RWTC", "EER_EPMRU_PF4_Y35NY_DPG", "EER_EPD2DXL0_PF4_Y35NY_DPG", "RNGWHHD"])
        self.assertEqual([s["data_vendor"] is not None for s in v["series"]], [False, False, False, False, True])
        self.assertIn("as EIA states", v["series"][4]["attribution"])
        self.assertEqual(v["credit"], fuels_fakes.fuels_sources.CREDIT)
        self.assertNotIn("fred_notice", v)
        self.assertEqual((v["snapshot"]["provider"], v["snapshot"]["retrieved_on"]), ("eia", "2026-11-06"))
        self.assertEqual((v["snapshots"][0]["provider"], v["snapshots"][0]["retrieved_on"]), ("eia", "2026-11-06"))
        self.assertNotIn(fuels_fakes.FAKE_KEY, json.dumps(v))
        self.assertEqual(v["snapshot"]["id"], self.world["snapshot_id"])
        self.assertEqual(len(v["snapshots"]), 1)
        self.assertEqual([c["id"] for c in v["coverage"]], ["wti", "henry_hub", "europe_gas", "urea", "helium"])
        self.assertTrue(v["crack_history"])

    def test_the_example_is_the_crack_arithmetic(self):
        e = fuels_view.EXAMPLE
        g, d, br = Fraction(e["gasoline"]), Fraction(e["diesel"]), Fraction(e["brent"])
        self.assertEqual(fuels_crack.exact_text(fuels_crack.basket_value(g, d)), e["basket"])
        self.assertEqual(fuels_crack.exact_text(fuels_crack.crack(g, d, br)), e["crack"])
        self.assertEqual(self.get()["example"], e)

    def test_reading_writes_nothing_and_makes_no_outside_request(self):
        attempts = []
        connect = socket.socket.connect

        def local_only(sock, address):
            if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
                attempts.append(address)
                raise AssertionError("an outside connection was attempted")
            return connect(sock, address)
        client = self.client()
        before = tree(self.content), tree(self.snapshots)
        with mock.patch.object(socket.socket, "connect", local_only):
            reply = client.get("/api/fuels")
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertIs(reply.json()["provider_called"], False)
        self.assertEqual(attempts, [])
        self.assertEqual((tree(self.content), tree(self.snapshots)), before)

    def test_no_snapshot_withholds_every_value(self):
        empty = self.root / "empty"
        empty.mkdir()
        v = self.get(snapshots=empty)
        self.assertEqual(v["barrel"]["state"], "withheld")
        self.assertEqual([s["state"] for s in v["series"]], ["missing"] * 5)
        self.assertEqual([s["kind"] for s in v["series"]], ["missing"] * 5)
        self.assertTrue(all(s["latest"] is None and s["history"] == [] for s in v["series"]))
        self.assertEqual(v["crack_history"], [])
        self.assertEqual(v["note"]["state"], "unbound")
        self.assertEqual(v["snapshot"]["state"], "missing")
        self.assertNotIn("80.00", json.dumps(v))

    def test_an_edited_snapshot_withholds_every_value(self):
        self.edit_snapshot(lambda d: d["series"]["RBRTE"]["observations"].append(["2026-11-04", "1.00"]))
        v = self.get()
        self.assertEqual(v["snapshot"]["state"], "changed")
        self.assertEqual(v["barrel"]["state"], "withheld")
        self.assertEqual([s["state"] for s in v["series"]], ["missing"] * 5)
        self.assertEqual(v["note"]["state"], "unbound")

    def test_a_refused_series_is_missing_and_withholds_the_barrel(self):
        self.refresh_over(rows={"EER_EPMRU_PF4_Y35NY_DPG": {"units": "$/BBL"}})  # gasoline's units differ
        v = self.get()
        states = {s["role"]: s["state"] for s in v["series"]}
        self.assertEqual(states["gasoline"], "refused")
        self.assertEqual(states["brent"], "verified")
        self.assertEqual(v["barrel"]["state"], "withheld")
        self.assertIn("gasoline", v["barrel"]["problem"])
        self.assertEqual(v["crack_history"], [])
        self.assertEqual(v["note"]["state"], "unbound")
        self.assertEqual(v["snapshots"][0]["refused"], 1)
        self.assertIn("units changed", [s for s in v["series"] if s["role"] == "gasoline"][0]["problem"])
        self.assertWithheld(v, "gasoline")

    def test_a_snapshot_from_fred_is_kept_and_listed_but_its_values_are_withheld(self):
        folder = self.root / "fred"
        snapshot_id = fuels_fakes.write_fred_snapshot(folder)
        before = tree(folder)
        v = self.get(snapshots=folder)
        self.assertEqual((v["snapshot"]["state"], v["snapshot"]["id"], v["snapshot"]["provider"]),
                         ("verified", snapshot_id, "fred"))
        self.assertEqual(v["snapshot"]["retrieved_on"], "2026-11-05")
        self.assertEqual({s["state"] for s in v["series"]}, {"terms_changed"})
        self.assertTrue(all("came from FRED" in s["problem"] for s in v["series"]))
        self.assertEqual(v["barrel"]["state"], "withheld")
        self.assertEqual([(row["id"], row["provider"]) for row in v["snapshots"]], [(snapshot_id, "fred")])
        self.assertNotIn("80.00", json.dumps({k: v[k] for k in ("series", "barrel", "crack_history")}))
        self.assertEqual(tree(folder), before)  # read, never rewritten
        fuels_fakes.write_snapshot(folder, retrieved=fuels_fakes.RETRIEVED)  # a later refresh from EIA
        after = self.get(snapshots=folder)
        self.assertEqual((after["snapshot"]["provider"], after["barrel"]["state"]), ("eia", "computed"))
        self.assertEqual([row["provider"] for row in after["snapshots"]], ["eia", "fred"])

    def test_changed_terms_withhold_that_series(self):
        path = self.content / "sources.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["series"][2]["basis"] += " Edited."
        path.write_text(json.dumps(record), encoding="utf-8")
        v = self.get()
        states = {s["role"]: s["state"] for s in v["series"]}
        self.assertEqual(states["gasoline"], "terms_changed")
        self.assertEqual(states["brent"], "verified")
        self.assertEqual(v["barrel"]["state"], "withheld")
        self.assertIn("refresh to apply it", [s for s in v["series"] if s["role"] == "gasoline"][0]["problem"])
        self.assertWithheld(v, "gasoline")

    def test_a_refresh_moves_the_note_to_then_and_now(self):
        fuels_fakes.write_snapshot(self.snapshots, "negative", fuels_fakes.RETRIEVED + timedelta(hours=2))
        v = self.get()
        self.assertEqual(v["note"]["state"], "earlier")
        self.assertEqual((v["note"]["then"]["brent"], v["note"]["now"]["brent"]), ("80.00", "115.00"))
        self.assertEqual(len(v["snapshots"]), 2)
        self.assertGreater(v["snapshots"][0]["retrieved_at"], v["snapshots"][1]["retrieved_at"])
        self.assertEqual(v["barrel"]["inputs"]["brent"]["shown"], "115.00")
        self.assertEqual([n["state"] for n in v["notes"]], ["earlier"])

    def test_a_short_history_is_not_padded(self):
        shutil.rmtree(self.snapshots)
        fuels_fakes.write_snapshot(self.snapshots, start=date(2026, 11, 3) - timedelta(days=30))
        v = self.get()
        for s in v["series"]:
            self.assertTrue(0 < len(s["history"]) < 30, (s["role"], len(s["history"])))
            self.assertEqual(s["history"][0][0], "2026-10-05")
        self.assertTrue(0 < len(v["crack_history"]) < 30)

    def test_history_is_limited_to_a_year_and_keeps_gaps(self):
        brent = self.get()["series"][0]
        self.assertGreater(date.fromisoformat(brent["history"][0][0]), date(2026, 11, 3) - timedelta(days=365))
        self.assertEqual(brent["latest"]["date"], "2026-11-03")
        data = fuels_fakes.datasets()
        day, _ = data["RBRTE"][-5]
        data["RBRTE"][-5] = (day, None)  # no value that day
        self.refresh_over(data)
        history = self.get()["series"][0]["history"]
        self.assertIn([day.isoformat(), None], history)


class Stage2(Fuels):
    STAGE1_KEYS = {"view_version", "provider_called", "page_label", "credit", "terms", "sources", "snapshot",
                   "snapshots", "series", "barrel", "crack_history", "note", "notes", "coverage", "example", "labels"}

    def stale_world(self):
        shutil.rmtree(self.snapshots)
        fuels_fakes.write_snapshot(self.snapshots, "positive", fuels_fakes.RETRIEVED + timedelta(days=14))

    def test_situation_is_computed_on_the_positive_world(self):
        v = self.get()
        s = v["situation"]
        self.assertEqual((v["view_version"], s["state"], s["date"]), ("fuels-view-0.5", "computed", "2026-11-03"))
        self.assertTrue(self.STAGE1_KEYS <= set(v))
        previous = s["windows"][0]
        self.assertEqual((previous["id"], previous["from"]), ("previous", "2026-11-02"))
        self.assertEqual(previous["split"]["crude"]["shown"], "0.96")
        basket = previous["rows"]["basket"]
        self.assertEqual(Fraction(basket["change"]["value"]),
                         Fraction(previous["split"]["crude"]["value"]) + Fraction(previous["split"]["crack"]["value"]))

    def test_the_missing_world_withholds_the_situation_but_keeps_the_mechanisms(self):
        empty = self.root / "empty"
        empty.mkdir()
        v = self.get(snapshots=empty)
        self.assertEqual(v["situation"]["state"], "withheld")
        self.assertEqual((v["drivers"]["state"], v["transmission"]["state"]), ("written", "written"))

    def test_the_stale_world_says_so(self):
        self.stale_world()
        s = self.get()["situation"]
        self.assertEqual((s["state"], s["stale"], s["age_days"]), ("computed", True, 17))

    def test_an_absent_mechanism_file_is_not_written(self):
        (self.content / "drivers.json").unlink()
        v = self.get()
        self.assertEqual(v["drivers"], {"state": "not_written"})
        self.assertEqual(v["transmission"]["state"], "written")

    def test_an_invalid_committed_drivers_file_is_500(self):
        (self.content / "drivers.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.client().get("/api/fuels").status_code, 500)

    def test_events_are_not_connected(self):
        e = self.get()["events"]
        self.assertEqual((e["state"], e["schema"]), ("not_connected", "fuels-event-0.1"))
        self.assertIn("No verified current events are connected", e["text"])
        self.assertIn("general possible explanations", e["text"])  # as the E legend calls them


class SyntheticMark(Fuels):
    def synthetic_client_get(self, snapshots: Path) -> dict:
        reply = self.accounts.client("admin", fuels_content=self.content, fuels_snapshots=snapshots,
                                     fuels_synthetic=True).get("/api/fuels")
        self.assertEqual(reply.status_code, 200, reply.text)
        return reply.json()

    def test_a_snapshot_from_the_fake_is_marked_wherever_it_is_served(self):
        """fuels_fakes answers as API version "SYNTHETIC-…", so a reply over its snapshot says synthetic even without
        the review server's flag: `serve --fuels-snapshots` over a copied fake folder still marks the prices."""
        self.assertIs(self.get()["synthetic"], True)

    def test_otherwise_only_the_server_flag_marks_the_reply_and_the_key_is_absent_rather_than_false(self):
        self.refresh_over(api_version="2.1.10")  # a version EIA itself could answer with
        self.assertEqual(self.get()["snapshot"]["state"], "verified")
        self.assertNotIn("synthetic", self.get())
        self.assertIs(self.synthetic_client_get(self.snapshots)["synthetic"], True)
        empty = self.root / "empty"
        empty.mkdir()
        self.assertNotIn("synthetic", self.get(snapshots=empty))
        self.assertIs(self.synthetic_client_get(empty)["synthetic"], True)

    def test_the_review_server_marks_its_synthetic_fuels_world_and_serve_does_not(self):
        server = (ROOT / "tests" / "review_browser_server.py").read_text(encoding="utf-8")
        self.assertIn('fuels_synthetic=args.fuels == "synthetic"', server)
        self.assertNotIn("fuels_synthetic", (ROOT / "second_order" / "__main__.py").read_text(encoding="utf-8"))


class Analysis(Fuels):
    """A fuels-note-0.2 bound to the world's snapshot: filled from that snapshot's barrel and Situation Now windows."""

    def setUp(self):
        super().setUp()
        fuels_fakes.write_analysis_note(self.content, self.snapshots)  # note 2, bound to the positive snapshot

    def texts(self, note):
        return [note["headline"], note["lede"], *(item["text"] for section in fuels_notes.SECTIONS
                                                   for item in note["analysis"][section])]

    def test_the_analysis_is_current_filled_and_names_its_mechanisms(self):
        note = self.get()["note"]
        self.assertEqual((note["state"], note["number"], note["note_version"]), ("current", 2, "fuels-note-0.2"))
        self.assertTrue(all("{" not in text for text in self.texts(note)))
        self.assertTrue(40 <= fuels_notes.words(note["lede"]) <= 70, fuels_notes.words(note["lede"]))
        self.assertIn("From 27 Oct 2026 to 3 Nov 2026", note["lede"])
        self.assertEqual([item["mechanism_title"] for item in note["analysis"]["relevance"]],
                         ["Refiners and oil producers", "Shipping, trucking and logistics"])
        self.assertEqual(note["analysis"]["meaning"][2]["mechanism_title"], "Inventories: crude stocks and product stocks")
        self.assertEqual((note["author"], note["review"]["state"]), ("Claude (AI-drafted)", "unreviewed"))

    def test_after_a_refresh_the_analysis_is_earlier_and_keeps_its_own_dates(self):
        fuels_fakes.write_snapshot(self.snapshots, "negative", fuels_fakes.RETRIEVED + timedelta(hours=2))
        note = self.get()["note"]
        self.assertEqual((note["state"], note["then"]["brent"], note["now"]["brent"]), ("earlier", "80.00", "115.00"))
        self.assertIn("From 27 Oct 2026 to 3 Nov 2026", note["lede"])

    def test_without_its_snapshot_the_analysis_is_unbound_and_never_filled(self):
        empty = self.root / "empty"
        empty.mkdir()
        note = self.get(snapshots=empty)["note"]
        self.assertEqual(note["state"], "unbound")
        self.assertIn("{week_from}", note["lede"])  # the page's reader shows no prose that still holds a placeholder

    def test_with_its_snapshot_changed_the_analysis_is_unbound(self):
        self.edit_snapshot(lambda d: d["series"]["RBRTE"]["observations"].append(["2026-11-04", "1.00"]))
        v = self.get()
        self.assertEqual((v["snapshot"]["state"], v["note"]["state"]), ("changed", "unbound"))

    def test_a_mechanism_that_is_not_committed_is_a_500(self):
        path = self.content / "notes" / "situation-0002.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["analysis"]["relevance"][0]["mechanism"] = "transmission:steel"
        path.write_text(json.dumps(data), encoding="utf-8")
        reply = self.client().get("/api/fuels")
        self.assertEqual(reply.status_code, 500)
        self.assertIn("relevance[0].mechanism", reply.json()["detail"])

    def test_the_committed_note_names_committed_mechanisms(self):
        content = fuels_fakes.fuels_sources.CONTENT_DIR
        titles = fuels_view._titles(fuels_mechanisms.load_drivers(content), fuels_mechanisms.load_transmission(content))
        for note in fuels_notes.load_notes(content):
            fuels_view._with_titles(note, titles)  # raises on a mechanism that is not committed


class Access(Fuels):
    def test_admins_only(self):
        self.assertEqual(self.client().get("/api/fuels").status_code, 200)
        reader = self.client(user="reader-a").get("/api/fuels")
        self.assertEqual(reader.status_code, 403)
        self.assertNotIn("80.00", reader.text)
        self.assertEqual(self.client(user=None).get("/api/fuels").status_code, 401)

    def test_it_is_a_read_only_route(self):
        app = self.accounts.app(fuels_content=self.content, fuels_snapshots=self.snapshots)
        methods = set()
        for route in app.routes:
            if getattr(route, "path", None) == "/api/fuels":
                methods |= set(route.methods)
        self.assertEqual(methods, {"GET"})

    def test_by_default_no_snapshot_is_read(self):
        self.assertIsNone(inspect.signature(create_app).parameters["fuels_snapshots"].default)

    def test_the_read_path_loads_no_network_module(self):
        code = ("import sys, second_order.fuels_api; "
                "print('second_order.fuels_eia' in sys.modules, 'second_order.fred' in sys.modules)")
        done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.stdout.strip(), "False False", done.stderr)


class Fixtures(Fuels):
    def test_frontend_fixtures(self):
        """The replies the frontend reader is tested against: captured from this producer, never hand-written."""
        served = {"fuels-view.json": self.get()}
        fuels_fakes.write_snapshot(self.snapshots, "negative", fuels_fakes.RETRIEVED + timedelta(hours=2))
        served["fuels-view-earlier.json"] = self.get()
        empty = self.root / "empty"
        empty.mkdir()
        served["fuels-view-missing.json"] = self.get(snapshots=empty)
        shutil.rmtree(self.snapshots)
        fuels_fakes.write_snapshot(self.snapshots, "positive", fuels_fakes.RETRIEVED + timedelta(days=14))
        served["fuels-view-stale.json"] = self.get()
        fuels_fakes.write_analysis_note(self.content, self.snapshots)  # an analysis bound to the stale snapshot
        served["fuels-view-analysis.json"] = self.get()
        for name, options in (("fuels-view-behind-wti.json", {"behind": {"wti": fuels_fakes.YEAR_BEHIND}}),
                              ("fuels-view-behind-diesel.json", {"behind": {"diesel": fuels_fakes.YEAR_BEHIND}}),
                              ("fuels-view-subcent.json", {"variant": "subcent"})):
            shutil.rmtree(self.snapshots)
            fuels_fakes.write_snapshot(self.snapshots, **options)
            served[name] = self.get()
        for name, reply in served.items():
            text = json.dumps(reply, ensure_ascii=False)
            self.assertNotIn(str(self.root), text, name)
            self.assertNotIn("second-order-fuels-api", text, name)
            path = FIXTURES / name
            if os.environ.get(WRITE_FIXTURES) == "1":
                path.write_bytes((json.dumps(reply, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            else:
                self.assertEqual(reply, json.loads(path.read_text(encoding="utf-8")),
                                 f"{name} is stale; regenerate it with {WRITE_FIXTURES}=1 python -m unittest discover "
                                 "-s tests -p test_fuels_api.py")


if __name__ == "__main__":
    unittest.main()
