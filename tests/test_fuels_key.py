"""The stored EIA key: kept in Windows Credential Manager through keyring, typed once at a hidden prompt, read by
`fuels refresh` when EIA_API_KEY is not set, and never printed. No test here reaches the real Credential Manager:
stores are in memory, the vault is a fake, and keyring's own backend is set to one that the store refuses by type and
that would fail on any use."""
import json
from pathlib import Path
import unittest

import keyring
from keyring.backends import fail
from keyring.errors import KeyringError

from fuels_fakes import FAKE_KEY, FakeVault, MemoryKeyStore as MemoryStore, OtherKeyring
from second_order import fuels_key

ROOT = Path(__file__).resolve().parent.parent
OTHER_KEY = "ZYXWVUTSRQPONMLKJIHGFEDCBA9876543210abcd"
_previous = None


def setUpModule():
    """Any path that slips past the fakes to keyring's default backend fails loudly instead of using the real vault."""
    global _previous
    _previous = keyring.get_keyring()
    keyring.set_keyring(fail.Keyring())


def tearDownModule():
    keyring.set_keyring(_previous)


class Prompt:
    """Answers getpass with the given entries and records the prompts it was shown."""

    def __init__(self, *answers):
        self.answers, self.prompts = list(answers), []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.answers.pop(0)


class RefreshKeyTests(unittest.TestCase):
    def test_eia_api_key_is_used_first(self):
        key, source = fuels_key.refresh_key({"EIA_API_KEY": f" {FAKE_KEY} "}, MemoryStore(OTHER_KEY))
        self.assertEqual((key, source), (FAKE_KEY, "EIA_API_KEY"))

    def test_the_stored_key_is_used_when_the_variable_is_unset_or_blank(self):
        for environ in ({}, {"EIA_API_KEY": "  "}):
            with self.subTest(environ=environ):
                self.assertEqual(fuels_key.refresh_key(environ, MemoryStore(FAKE_KEY)),
                                 (FAKE_KEY, "Windows Credential Manager"))

    def test_without_either_the_refusal_names_both_ways(self):
        with self.assertRaises(fuels_key.KeyRefused) as raised:
            fuels_key.refresh_key({}, MemoryStore())
        self.assertIn("EIA_API_KEY", str(raised.exception))
        self.assertIn("python -m second_order fuels key set", str(raised.exception))

    def test_an_unreadable_store_still_names_the_variable(self):
        class Unreadable(MemoryStore):
            def get(self):
                raise fuels_key.KeyRefused("A stored key needs the keyring package: pip install -r requirements.txt")
        with self.assertRaises(fuels_key.KeyRefused) as raised:
            fuels_key.refresh_key({}, Unreadable())
        self.assertIn("EIA_API_KEY is not set", str(raised.exception))
        self.assertIn("keyring", str(raised.exception))

    def test_the_store_is_not_read_when_the_variable_is_set(self):
        class Unreadable(MemoryStore):
            def get(self):
                raise AssertionError("the store was read")
        self.assertEqual(fuels_key.refresh_key({"EIA_API_KEY": FAKE_KEY}, Unreadable())[1], "EIA_API_KEY")


class StatusTests(unittest.TestCase):
    def test_status_says_only_whether_a_key_is_there(self):
        cases = [({}, None, False, False, None, "python -m second_order fuels key set"),
                 ({}, FAKE_KEY, True, False, "Windows Credential Manager", "python -m second_order fuels refresh"),
                 ({"EIA_API_KEY": FAKE_KEY}, None, False, True, "EIA_API_KEY", "python -m second_order fuels refresh"),
                 ({"EIA_API_KEY": FAKE_KEY}, OTHER_KEY, True, True, "EIA_API_KEY",
                  "python -m second_order fuels refresh")]
        for environ, stored, has, env_set, reads, after in cases:
            with self.subTest(environ=bool(environ), stored=bool(stored)):
                report = fuels_key.status(environ, MemoryStore(stored))
                self.assertEqual(report, {"stored": has, "store": "Windows Credential Manager",
                                          "EIA_API_KEY_set": env_set, "refresh_reads": reads, "next": after})
                text = json.dumps(report)
                self.assertNotIn(FAKE_KEY, text)
                self.assertNotIn(OTHER_KEY, text)


class SaveTests(unittest.TestCase):
    def test_set_asks_twice_hidden_and_stores_the_trimmed_key(self):
        store, ask = MemoryStore(), Prompt(f"  {FAKE_KEY}\n", FAKE_KEY)
        report = fuels_key.save(False, store, ask, interactive=True)
        self.assertEqual(store.key, FAKE_KEY)
        self.assertEqual(len(ask.prompts), 2)
        self.assertEqual(report, {"stored": True, "replaced": False, "store": "Windows Credential Manager",
                                  "refreshed": False, "next": "python -m second_order fuels refresh"})
        self.assertNotIn(FAKE_KEY, json.dumps(report) + "".join(ask.prompts))

    def test_set_refuses_without_a_terminal_and_asks_nothing(self):
        store, ask = MemoryStore(), Prompt(FAKE_KEY, FAKE_KEY)
        with self.assertRaises(fuels_key.KeyRefused) as raised:
            fuels_key.save(False, store, ask, interactive=False)
        self.assertIn("terminal", str(raised.exception))
        self.assertEqual((store.key, ask.prompts), (None, []))

    def test_set_refuses_when_a_key_is_stored_before_asking(self):
        store, ask = MemoryStore(OTHER_KEY), Prompt(FAKE_KEY, FAKE_KEY)
        with self.assertRaises(fuels_key.KeyRefused) as raised:
            fuels_key.save(False, store, ask, interactive=True)
        self.assertIn("fuels key replace", str(raised.exception))
        self.assertEqual((store.key, ask.prompts), (OTHER_KEY, []))

    def test_replace_overwrites(self):
        store = MemoryStore(OTHER_KEY)
        report = fuels_key.save(True, store, Prompt(FAKE_KEY, FAKE_KEY), interactive=True)
        self.assertEqual(store.key, FAKE_KEY)
        self.assertTrue(report["replaced"])
        self.assertFalse(report["refreshed"])

    def test_bad_entries_store_nothing_and_are_not_echoed(self):
        cases = {"differ": (FAKE_KEY, OTHER_KEY), "empty": ("   ", "   "), "space": ("abc def", "abc def"),
                 "control": ("abc\x07def", "abc\x07def"), "non-ascii": ("abcdéf", "abcdéf"),
                 "long": ("a" * 257, "a" * 257)}
        for name, answers in cases.items():
            with self.subTest(name):
                store = MemoryStore(OTHER_KEY)
                with self.assertRaises(fuels_key.KeyRefused) as raised:
                    fuels_key.save(True, store, Prompt(*answers), interactive=True)
                self.assertEqual(store.key, OTHER_KEY)
                message = str(raised.exception)
                self.assertIn("nothing was stored", message)
                for answer in answers:
                    if answer.strip():
                        self.assertNotIn(answer.strip(), message)

    def test_the_longest_accepted_entry(self):
        store = MemoryStore()
        fuels_key.save(False, store, Prompt("a" * 256, "a" * 256), interactive=True)
        self.assertEqual(store.key, "a" * 256)


class DeleteTests(unittest.TestCase):
    def test_delete_removes_and_says_whether_there_was_one(self):
        store = MemoryStore(FAKE_KEY)
        self.assertEqual(fuels_key.delete(store), {"deleted": True, "store": "Windows Credential Manager"})
        self.assertIsNone(store.key)
        self.assertEqual(fuels_key.delete(store), {"deleted": False, "store": "Windows Credential Manager"})


class KeyringStoreTests(unittest.TestCase):
    def test_the_vault_holds_one_named_entry(self):
        vault = FakeVault()
        store = fuels_key.KeyringStore(vault)
        self.assertIsNone(store.get())
        store.put(FAKE_KEY)
        self.assertEqual(vault.entries, {(fuels_key.SERVICE, fuels_key.ACCOUNT): FAKE_KEY})
        self.assertEqual(store.get(), FAKE_KEY)
        self.assertTrue(store.delete())
        self.assertEqual(vault.entries, {})
        self.assertFalse(store.delete())

    def test_a_vault_that_does_not_keep_the_key_is_reported(self):
        with self.assertRaises(fuels_key.KeyRefused) as raised:
            fuels_key.KeyringStore(FakeVault(keep=False)).put(FAKE_KEY)
        self.assertIn("did not return", str(raised.exception))

    def test_backend_errors_name_only_their_type(self):
        class Broken(FakeVault):
            def get_password(self, *_):
                raise KeyringError(f"vault said {FAKE_KEY}")
            set_password = delete_password = get_password
        store = fuels_key.KeyringStore(Broken())
        for call in (store.get, lambda: store.put(FAKE_KEY), store.delete):
            with self.assertRaises(fuels_key.KeyRefused) as raised:
                call()
            self.assertIn("KeyringError", str(raised.exception))
            self.assertNotIn(FAKE_KEY, str(raised.exception))



class OtherStoreTests(unittest.TestCase):
    """Any keyring backend but Windows Credential Manager's is refused before a single call is made on it."""

    def assert_refused_unused(self, call, backend) -> str:
        with self.assertRaises(fuels_key.KeyRefused) as raised:
            call()
        message = str(raised.exception)
        self.assertIn("not using Windows Credential Manager", message)
        self.assertIn("OtherKeyring", message)
        self.assertNotIn(FAKE_KEY, message)
        self.assertEqual(backend.calls, [])
        return message

    def test_reading_storing_and_removing_are_refused_before_use(self):
        for name, call in (("get", lambda store: store.get()), ("put", lambda store: store.put(OTHER_KEY)),
                           ("delete", lambda store: store.delete())):
            with self.subTest(name):
                backend = OtherKeyring()
                self.assert_refused_unused(lambda: call(fuels_key.KeyringStore(backend)), backend)
                self.assertEqual(backend.key, FAKE_KEY)

    def test_status_is_refused_before_use(self):
        for environ in ({}, {"EIA_API_KEY": OTHER_KEY}):
            with self.subTest(environ=bool(environ)):
                backend = OtherKeyring()
                self.assert_refused_unused(lambda: fuels_key.status(environ, fuels_key.KeyringStore(backend)), backend)

    def test_a_refresh_without_the_variable_is_refused_before_use(self):
        backend = OtherKeyring()
        message = self.assert_refused_unused(lambda: fuels_key.refresh_key({}, fuels_key.KeyringStore(backend)),
                                             backend)
        self.assertIn("EIA_API_KEY is not set", message)

    def test_a_refresh_with_the_variable_never_reaches_the_store(self):
        backend = OtherKeyring()
        self.assertEqual(fuels_key.refresh_key({"EIA_API_KEY": OTHER_KEY}, fuels_key.KeyringStore(backend)),
                         (OTHER_KEY, "EIA_API_KEY"))
        self.assertEqual(backend.calls, [])

    def test_set_replace_and_delete_are_refused_before_use(self):
        for replace in (False, True):
            with self.subTest(replace=replace):
                backend, ask = OtherKeyring(), Prompt(OTHER_KEY, OTHER_KEY)
                self.assert_refused_unused(
                    lambda: fuels_key.save(replace, fuels_key.KeyringStore(backend), ask, interactive=True), backend)
                self.assertEqual(ask.prompts, [])
        backend = OtherKeyring()
        self.assert_refused_unused(lambda: fuels_key.delete(fuels_key.KeyringStore(backend)), backend)

    def test_keyrings_own_backend_is_checked_too(self):
        """keyring's backend in this module is its fail backend. The default store refuses it by type, so the call that
        would raise NoKeyringError is never made."""
        for call in (lambda: fuels_key.default_store().get(), lambda: fuels_key.default_store().delete()):
            with self.assertRaises(fuels_key.KeyRefused) as raised:
                call()
            self.assertIn("not using Windows Credential Manager here (Keyring)", str(raised.exception))
            self.assertNotIn("NoKeyringError", str(raised.exception))


class WhereTheKeyGoesTests(unittest.TestCase):
    def test_the_server_and_the_page_never_read_it(self):
        for name in ("api.py", "fuels_api.py", "fuels_view.py", "fuels_snapshots.py", "fuels_sources.py"):
            text = (ROOT / "second_order" / name).read_text(encoding="utf-8")
            with self.subTest(name):
                for word in ("fuels_key", "keyring", "EIA_API_KEY"):
                    self.assertNotIn(word, text)

    def test_saving_a_key_cannot_refresh(self):
        text = (ROOT / "second_order" / "fuels_key.py").read_text(encoding="utf-8")
        for word in ("httpx", "fuels_eia", "refresh_report", "import refresh"):
            self.assertNotIn(word, text)

    def test_the_key_is_never_a_command_line_argument(self):
        from second_order.__main__ import main
        import io
        import sys
        from unittest import mock
        for action in ("set", "replace", "delete", "status"):
            argv = ["second_order", "fuels", "key", action, "--help"]
            with (mock.patch.object(sys, "argv", argv), mock.patch("sys.stdout", new_callable=io.StringIO) as out,
                  self.assertRaises(SystemExit)):
                main()
            options = {word.strip("[],") for word in out.getvalue().split() if word.strip("[],").startswith("-")}
            self.assertEqual(options, {"--help", "-h"}, action)


if __name__ == "__main__":
    unittest.main()
