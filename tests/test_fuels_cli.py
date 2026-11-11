"""The fuels commands: reports carry dates, states and counts, never a price, change or crack value."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import keyring
from keyring.backends import fail
from fuels_fakes import FAKE_KEY, RETRIEVED, FakeEia, FakeVault, MemoryKeyStore, OtherKeyring, datasets
from second_order import fuels_key, fuels_snapshots, fuels_sources
from second_order.__main__ import main
from second_order.fuels_cli import refresh_report, status_report

CONTENT = fuels_sources.CONTENT_DIR
ROOT = Path(__file__).resolve().parent.parent
# A command run here never reaches the real Windows Credential Manager: keyring's null backend is not its backend,
# so the key commands and a refresh without EIA_API_KEY refuse it before any use.
NO_STORED_KEY = {"PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"}
_previous = None


def setUpModule():
    """In-process, keyring's backend fails on any use, so a path that slips past the fakes fails instead."""
    global _previous
    _previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())


def tearDownModule():
    keyring.set_keyring(_previous)


def keys_in(value) -> set:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_in(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_in(v)}
    return set()


def command(*args, env=None, stdin=subprocess.DEVNULL):
    env = {**(os.environ if env is None else env), **NO_STORED_KEY}
    return subprocess.run([sys.executable, "-m", "second_order", *args], cwd=ROOT, capture_output=True, text=True,
                          env=env, stdin=stdin, timeout=60)  # a prompt that waits on the console fails, not hangs


class FuelsCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.snapshots = Path(self._tmp.name) / "snapshots"

    def test_reports_carry_no_values(self):
        report = refresh_report(self.snapshots, CONTENT, FAKE_KEY, None, FakeEia(datasets()).client(),
                                lambda: RETRIEVED)
        status = status_report(CONTENT, self.snapshots)
        latest_payload = fuels_snapshots.load_all(self.snapshots)["snapshots"][-1]
        raws = {raw for entry in latest_payload["series"].values() for _, raw in entry["observations"] if raw}
        text = json.dumps([report, status])
        self.assertTrue(raws)
        self.assertEqual([raw for raw in raws if raw in text], [])
        self.assertEqual(keys_in([report, status]) & {"value", "shown", "basket", "crack", "change", "inputs"},
                         set())
        self.assertEqual(status["latest"]["barrel_date"], "2026-11-03")
        self.assertEqual(report["next"], "python -m second_order fuels status")
        self.assertEqual(status["snapshots"], 1)
        self.assertEqual(status["latest"]["snapshot_id"], report["snapshot_id"])
        self.assertEqual((status["latest"]["provider"], status["latest"]["retrieved_on"]), ("eia", "2026-11-06"))
        self.assertEqual({s["publication_date"] for s in status["latest"]["series"].values()}, {None})
        self.assertNotIn(FAKE_KEY, text)

    def test_status_without_snapshots(self):
        status = status_report(CONTENT, self.snapshots)
        self.assertEqual(status["snapshots"], 0)
        self.assertIsNone(status["latest"])

    def test_without_a_key_nothing_is_requested(self):
        env = {k: v for k, v in os.environ.items() if k not in ("EIA_API_KEY", "FRED_API_KEY")}
        done = command("fuels", "refresh", "--snapshots", str(self.snapshots), env=env)
        self.assertEqual(done.returncode, 1)
        self.assertIn("EIA_API_KEY", done.stderr)
        self.assertFalse(self.snapshots.exists())
        blank = command("fuels", "refresh", "--snapshots", str(self.snapshots), env={**env, "EIA_API_KEY": "  "})
        self.assertEqual(blank.returncode, 1)
        self.assertIn("EIA_API_KEY", blank.stderr)
        for done in (done, blank):
            self.assertIn("EIA_API_KEY is not set", done.stderr)
            self.assertIn("keyring is not using Windows Credential Manager here (Keyring)", done.stderr)

    def test_a_provider_failure_prints_failed_without_the_key_and_writes_nothing(self):
        """The refresh path end to end through main(): EIA answers 403 with the key in its message."""
        fake = FakeEia(datasets(), status={"RBRTE": (403, {"error": {"code": "API_KEY_INVALID", "message": "{KEY}"}})})
        argv = ["second_order", "fuels", "refresh", "--snapshots", str(self.snapshots)]
        import httpx
        real_client = httpx.Client
        with (mock.patch.object(sys, "argv", argv), mock.patch.dict(os.environ, {"EIA_API_KEY": FAKE_KEY}),
              mock.patch("httpx.Client", lambda **_: real_client(transport=httpx.MockTransport(fake))),
              mock.patch("sys.stderr") as stderr, mock.patch("sys.stdout")):
            self.assertEqual(main(), 1)
        written = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("Failed: EIA request for RBRTE returned HTTP 403 (API_KEY_INVALID)", written)
        self.assertNotIn(FAKE_KEY, written)
        self.assertFalse(self.snapshots.exists())

    def run_main(self, argv, store=None, environ=None):
        """main() in process with the given key store (default: an empty one in memory); returns (exit code, stdout,
        stderr, FakeEia)."""
        import io
        import httpx
        fake, real_client = FakeEia(datasets()), httpx.Client
        environ = {k: v for k, v in os.environ.items() if k != "EIA_API_KEY"} | (environ or {})
        with (mock.patch.object(sys, "argv", ["second_order", *argv]), mock.patch.dict(os.environ, environ, clear=True),
              mock.patch.object(fuels_key, "default_store", lambda: MemoryKeyStore() if store is None else store),
              mock.patch("httpx.Client", lambda **_: real_client(transport=httpx.MockTransport(fake))),
              mock.patch("sys.stdout", new_callable=io.StringIO) as out,
              mock.patch("sys.stderr", new_callable=io.StringIO) as err):
            code = main()
        return code, out.getvalue(), err.getvalue(), fake

    def test_refresh_reads_the_stored_key_when_the_variable_is_unset(self):
        store = fuels_key.KeyringStore(FakeVault(FAKE_KEY))
        code, out, err, fake = self.run_main(["fuels", "refresh", "--snapshots", str(self.snapshots)], store)
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.keys, [FAKE_KEY] * 5)
        self.assertEqual(json.loads(out)["key_from"], "Windows Credential Manager")
        written = b"".join(path.read_bytes() for path in self.snapshots.iterdir())
        self.assertNotIn(FAKE_KEY, out + err)
        self.assertNotIn(FAKE_KEY.encode(), written)

    def test_the_variable_overrides_the_stored_key(self):
        other = "ZYXWVUTSRQPONMLKJIHGFEDCBA9876543210abcd"
        store = fuels_key.KeyringStore(FakeVault(other))
        code, out, err, fake = self.run_main(["fuels", "refresh", "--snapshots", str(self.snapshots)], store,
                                             environ={"EIA_API_KEY": FAKE_KEY})
        self.assertEqual(code, 0, err)
        self.assertEqual(set(fake.keys), {FAKE_KEY})
        self.assertEqual(json.loads(out)["key_from"], "EIA_API_KEY")
        self.assertNotIn(other, out + err)

    def test_with_the_variable_set_another_store_is_never_touched(self):
        backend = OtherKeyring("ZYXWVUTSRQPONMLKJIHGFEDCBA9876543210abcd")
        code, out, err, fake = self.run_main(["fuels", "refresh", "--snapshots", str(self.snapshots)],
                                             fuels_key.KeyringStore(backend), environ={"EIA_API_KEY": FAKE_KEY})
        self.assertEqual(code, 0, err)
        self.assertEqual(set(fake.keys), {FAKE_KEY})
        self.assertEqual(backend.calls, [])

    def test_without_the_variable_another_store_is_refused_before_use(self):
        backend = OtherKeyring()
        code, out, err, fake = self.run_main(["fuels", "refresh", "--snapshots", str(self.snapshots)],
                                             fuels_key.KeyringStore(backend))
        self.assertEqual(code, 1)
        self.assertIn("not using Windows Credential Manager here (OtherKeyring)", err)
        self.assertEqual((backend.calls, fake.keys, out), ([], [], ""))
        self.assertFalse(self.snapshots.exists())

    def test_saving_a_key_stores_it_and_requests_nothing(self):
        store = MemoryKeyStore()
        with (mock.patch.object(fuels_key, "default_store", lambda: store),
              mock.patch.object(fuels_key, "_interactive", lambda: True),
              mock.patch("getpass.getpass", side_effect=[FAKE_KEY, FAKE_KEY]),
              mock.patch("httpx.Client", side_effect=AssertionError("a request was made")),
              mock.patch.object(sys, "argv", ["second_order", "fuels", "key", "set"]),
              mock.patch("sys.stdout") as stdout, mock.patch("sys.stderr")):
            self.assertEqual(main(), 0)
        printed = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertEqual(store.key, FAKE_KEY)
        self.assertFalse(json.loads(printed)["refreshed"])
        self.assertNotIn(FAKE_KEY, printed)

    def test_key_status_prints_presence_only(self):
        code, out, err, _ = self.run_main(["fuels", "key", "status"], fuels_key.KeyringStore(FakeVault()))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {"stored": False, "store": "Windows Credential Manager",
                                           "EIA_API_KEY_set": False, "refresh_reads": None,
                                           "next": "python -m second_order fuels key set"})
        code, out, err, _ = self.run_main(["fuels", "key", "status"], fuels_key.KeyringStore(FakeVault(FAKE_KEY)),
                                          environ={"EIA_API_KEY": FAKE_KEY})
        self.assertEqual(code, 0, err)
        self.assertEqual((json.loads(out)["stored"], json.loads(out)["refresh_reads"]), (True, "EIA_API_KEY"))
        self.assertNotIn(FAKE_KEY, out + err)

    def test_key_commands_refuse_another_store(self):
        """Through real processes: keyring's null backend is not Windows Credential Manager's, so each refuses."""
        for action in ("status", "delete"):
            with self.subTest(action):
                done = command("fuels", "key", action)
                self.assertEqual(done.returncode, 1, done.stderr)
                self.assertTrue(done.stderr.startswith(
                    "Failed: keyring is not using Windows Credential Manager here (Keyring)"), done.stderr)
                self.assertEqual(done.stdout, "")

    def test_key_set_without_a_terminal_refuses_at_once(self):
        done = command("fuels", "key", "set")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertTrue(done.stderr.startswith("Failed: "), done.stderr)
        self.assertIn("terminal", done.stderr)
        self.assertEqual(done.stdout, "")

    def test_status_command_prints_json(self):
        done = command("fuels", "status", "--snapshots", str(self.snapshots))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["snapshots"], 0)

    def test_the_commands_are_listed(self):
        done = command("fuels", "--help")
        self.assertEqual(done.returncode, 0)
        self.assertIn("refresh", done.stdout)
        self.assertIn("status", done.stdout)
        self.assertIn("key", done.stdout)
        key = command("fuels", "key", "--help")
        self.assertEqual(key.returncode, 0, key.stderr)
        for action in ("set", "replace", "delete", "status"):
            self.assertIn(action, key.stdout)

    def test_a_refused_read_prints_failed_not_a_traceback(self):
        content = Path(self._tmp.name) / "content"
        (content / "notes").mkdir(parents=True)
        shutil.copyfile(CONTENT / fuels_sources.SOURCES_FILE, content / fuels_sources.SOURCES_FILE)
        (content / "notes" / "situation-0001.json").write_text("{}", encoding="utf-8")
        done = command("fuels", "status", "--content", str(content), "--snapshots", str(self.snapshots))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertTrue(done.stderr.startswith("Failed: notes/situation-0001.json"), done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertEqual(done.stdout, "")


class ServeFuelsSnapshotsTests(unittest.TestCase):
    """`serve --fuels-snapshots PATH` lets a worktree's server read another checkout's snapshots. No server starts:
    uvicorn.run and create_app are replaced, and only the arguments create_app receives are read."""

    def test_serve_lists_the_option(self):
        done = command("serve", "--help")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("--fuels-snapshots", done.stdout)

    def serve_with(self, *extra) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            accounts = Path(tmp) / "accounts.db"
            accounts.write_bytes(b"")  # serve requires the file to exist; create_app is replaced, so it is never read
            argv = ["second_order", "serve", "--accounts", str(accounts), *extra]
            with (mock.patch.object(sys, "argv", argv), mock.patch("uvicorn.run") as run,
                  mock.patch("second_order.api.create_app", return_value="app") as create):
                self.assertEqual(main(), 0)
            run.assert_called_once()
            self.assertEqual(run.call_args.args, ("app",))
            return create.call_args.kwargs

    def test_serve_reads_its_own_checkout_by_default(self):
        self.assertEqual(self.serve_with()["fuels_snapshots"], fuels_snapshots.SNAPSHOTS_DIR)

    def test_serve_reads_the_named_folder(self):
        folder = Path(tempfile.gettempdir()) / "second-order-v2" / "data" / "fuels" / "snapshots"
        self.assertEqual(self.serve_with("--fuels-snapshots", str(folder))["fuels_snapshots"], folder)


if __name__ == "__main__":
    unittest.main()
