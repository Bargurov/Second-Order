"""The EIA API key, stored once in Windows Credential Manager (through keyring) so a refresh needs no typing.

`fuels key set` takes the key at a hidden prompt, twice, and stores it; `replace` changes it, `delete` removes it and
`status` says only whether one is there. `fuels refresh` uses EIA_API_KEY when it is set and the stored key otherwise.
Only the fuels commands import this module: the server, the page and the snapshots never read the key. Nothing here
prints, logs or returns the key, except refresh_key(), whose one caller hands it to the EIA request. Saving a key
requests nothing and refreshes nothing. A keyring backend other than Windows Credential Manager's is refused before
any use, for reading and removing as for storing.
"""
import getpass
import os
import sys

ENV = "EIA_API_KEY"
SERVICE = "second-order-v2 EIA API key"  # the entry's name under Windows Credentials in Credential Manager
ACCOUNT = "EIA_API_KEY"
STORE_NAME = "Windows Credential Manager"
LONGEST = 256  # an EIA key is 40 characters; anything far longer is a paste gone wrong
SET, REPLACE, DELETE, REFRESH = (f"python -m second_order fuels {action}"
                                 for action in ("key set", "key replace", "key delete", "refresh"))


class KeyRefused(ValueError):
    """A refusal: main() prints it as "Failed: <message>". No message ever holds the key."""


class KeyringStore:
    """The key's one entry in Windows Credential Manager. A backend may be given (tests); the default is keyring's.
    Every read, write and removal goes through _backend(), which refuses any other backend before it is used."""

    def __init__(self, backend=None):
        self._given = backend

    def _backend(self):
        """Windows Credential Manager's backend, or a refusal before any call on another (a plain-text file, say)."""
        backend = self._given
        if backend is None:
            try:
                import keyring
            except ImportError:
                raise KeyRefused("A stored key needs the keyring package: pip install -r requirements.txt") from None
            backend = keyring.get_keyring()
        from keyring.backends.Windows import WinVaultKeyring
        if not isinstance(backend, WinVaultKeyring):
            raise KeyRefused(f"keyring is not using {STORE_NAME} here ({type(backend).__name__}); the key is read, "
                             "stored and removed only there, so nothing was read, stored or removed")
        return backend

    def get(self) -> str | None:
        backend = self._backend()
        try:
            return backend.get_password(SERVICE, ACCOUNT) or None
        except Exception as exc:  # The backend's text is not trusted to be free of the key; only its type is shown.
            raise KeyRefused(f"{STORE_NAME} could not be read ({type(exc).__name__})") from None

    def put(self, key: str) -> None:
        backend = self._backend()
        try:
            backend.set_password(SERVICE, ACCOUNT, key)
        except Exception as exc:
            raise KeyRefused(f"{STORE_NAME} could not be written ({type(exc).__name__})") from None
        if self.get() != key:
            raise KeyRefused(f"{STORE_NAME} did not return the key it was given; check with "
                             "python -m second_order fuels key status")

    def delete(self) -> bool:
        if self.get() is None:
            return False
        try:
            self._backend().delete_password(SERVICE, ACCOUNT)
        except Exception as exc:
            raise KeyRefused(f"{STORE_NAME} could not be cleared ({type(exc).__name__})") from None
        return True


def default_store() -> KeyringStore:
    return KeyringStore()


def _interactive() -> bool:
    """A real terminal on stdin. On Windows isatty() is also true for NUL, where the hidden prompt would wait on the
    console forever, so the handle must be a console that answers GetConsoleMode."""
    if sys.stdin is None or not sys.stdin.isatty():
        return False
    if os.name != "nt":
        return True
    import ctypes
    import msvcrt
    mode = ctypes.c_ulong()
    return bool(ctypes.windll.kernel32.GetConsoleMode(msvcrt.get_osfhandle(sys.stdin.fileno()), ctypes.byref(mode)))


def _environment(environ) -> str:
    return (os.environ if environ is None else environ).get(ENV, "").strip()


def refresh_key(environ=None, store=None) -> tuple[str, str]:
    """The key a refresh sends and where it came from: EIA_API_KEY when set, else the stored key."""
    key = _environment(environ)
    if key:
        return key, ENV
    try:
        stored = (default_store() if store is None else store).get()
    except KeyRefused as exc:
        raise KeyRefused(f"{ENV} is not set, and the stored key could not be read: {exc}") from None
    if stored:
        return stored, STORE_NAME
    raise KeyRefused(f"No EIA key: {ENV} is not set and {STORE_NAME} holds none. Store one once with {SET}")


def status(environ=None, store=None) -> dict:
    stored = (default_store() if store is None else store).get() is not None  # the key itself is dropped here
    env_set = bool(_environment(environ))
    reads = ENV if env_set else STORE_NAME if stored else None
    return {"stored": stored, "store": STORE_NAME, "EIA_API_KEY_set": env_set, "refresh_reads": reads,
            "next": REFRESH if reads else SET}


def _checked(entry: str) -> str:
    key = entry.strip()
    if not key:
        raise KeyRefused("No key was entered; nothing was stored")
    if len(key) > LONGEST:
        raise KeyRefused(f"The entry is longer than {LONGEST} characters; nothing was stored")
    if not (key.isascii() and key.isprintable()) or any(char.isspace() for char in key):
        raise KeyRefused("The entry holds a space or a character outside printable ASCII; nothing was stored")
    return key


def save(replace: bool, store=None, ask=None, interactive=None) -> dict:
    """Takes the key at a hidden prompt, twice, and stores it. Refuses before asking when there is no terminal, or
    when a key is already stored and this is not a replace."""
    store = default_store() if store is None else store
    if not (_interactive() if interactive is None else interactive):
        raise KeyRefused("The key is typed at a hidden prompt: run this in your own terminal window, not through a "
                         "pipe, a script or a chat")
    had = store.get() is not None
    if had and not replace:
        raise KeyRefused(f"A key is already stored; nothing changed. Change it with {REPLACE}, or remove it with "
                         f"{DELETE}")
    ask = getpass.getpass if ask is None else ask
    key = _checked(ask("EIA API key (typing is hidden): "))
    if ask("The same key again, to confirm: ").strip() != key:
        raise KeyRefused("The two entries differ; nothing was stored")
    store.put(key)
    return {"stored": True, "replaced": had, "store": STORE_NAME, "refreshed": False, "next": REFRESH}


def delete(store=None) -> dict:
    return {"deleted": (default_store() if store is None else store).delete(), "store": STORE_NAME}


def run(action: str) -> dict:
    if action == "status":
        return status()
    if action == "delete":
        return delete()
    return save(replace=action == "replace")
