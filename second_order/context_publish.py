"""Publishing a finished market-context bundle, and what an interrupted publication leaves behind.

Publication is two directory renames, made under the bundle's write lock (see context_lock): the live bundle is moved
aside into a folder beside it, then the finished folder moves into its place. The pair is not crash-atomic. Between
the renames the bundle path is briefly absent, so a reader at that instant finds no bundle.

The moved-aside folder's name records its owner and its time, and nothing else is written: it is
`.market-context-previous-<UTC time to the microsecond>-<8 hex digits>-<the bundle folder's exact name>`. The hex
digits never contain "-", so the owner parses back exactly (`market-context` is not `market-context-b`). Folders an
earlier version made record no owner and are never attributed to a bundle.

Ctrl-C (SIGINT) in the main thread is held until both renames, or the restoration after a failed one, have finished,
and is then delivered to whatever handled it before (by default, a KeyboardInterrupt noting how publication ended).
Nothing can hold an uncatchable kill, a power loss or an interrupt in another thread: if one stops publication between
the renames, the bundle path stays missing and the original stays intact in its moved-aside folder. `moved_aside` lists
such folders and `recovery_report` describes them. Nothing here chooses, restores, deletes or overwrites one; the
operator decides.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import re
import secrets
import shutil
import signal

PREVIOUS_PREFIX = ".market-context-previous-"  # Moved-aside originals; working folders are ".market-context-<letters>".
# This version's names: time (to the microsecond), a random token, then the owning bundle folder's exact name.
OWNED = re.compile(re.escape(PREVIOUS_PREFIX) + r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(\d{6})Z-[0-9a-f]{8}-(.+)")
# An earlier version's names: a time to the second, or no time, and no owner.
UNOWNED_TIMESTAMPED = re.compile(re.escape(PREVIOUS_PREFIX) + r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z-")


class PublicationFailed(Exception):
    """Nothing new was published; the message says so and where the original bundle is."""


class _Held:
    def __init__(self):
        self.pending = False

    def deliver(self, note: str) -> None:
        """After the block: a held Ctrl-C goes to whatever handled it before. If that raises KeyboardInterrupt (Python's
        default), `note` says how the held work ended; an ignored or custom-handled signal is left to its handler."""
        if self.pending:
            self.pending = False
            try:
                signal.raise_signal(signal.SIGINT)
            except KeyboardInterrupt as stop:
                stop.add_note(note)
                raise


@contextmanager
def ctrl_c_held():
    """Holds Ctrl-C until the block has ended; call deliver() after it. Only the main thread can change signal
    handling; elsewhere the block runs without this protection and nothing is held."""
    held = _Held()
    try:
        earlier = signal.signal(signal.SIGINT, lambda signum, frame: setattr(held, "pending", True))
    except ValueError:  # Not the main thread.
        yield held
        return
    try:
        yield held
    finally:
        signal.signal(signal.SIGINT, earlier if earlier is not None else signal.SIG_DFL)


def _reason(exc: OSError) -> str:
    return f"{type(exc).__name__}: {exc.strerror or exc}"


def _aside_name(out: Path) -> Path:
    """An unused path beside `out` whose name records the time and `out` as its owner (see the module docstring)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    for _ in range(100):
        path = out.parent / f"{PREVIOUS_PREFIX}{stamp}-{secrets.token_hex(4)}-{out.name}"
        try:
            path.mkdir()  # Reserves the name, as tempfile.mkdtemp would; the original is renamed onto it below.
        except FileExistsError:
            continue
        path.rmdir()
        return path
    raise FileExistsError(f"No unused name for a moved-aside folder beside {out}")


def _move(out: Path, work: Path) -> Path | None:
    """The two renames. Returns the moved-aside original (None if there was none); PublicationFailed otherwise."""
    previous = None
    if out.exists():
        try:
            previous = _aside_name(out)
            out.rename(previous)
        except OSError as exc:
            raise PublicationFailed(f"Publication did not occur: the existing bundle could not be moved aside "
                                    f"({_reason(exc)}). It is unchanged at {out}") from None
    try:
        work.rename(out)
    except OSError as exc:
        if previous is None:
            raise PublicationFailed(f"Publication did not occur: the new bundle could not be moved into place at {out} "
                                    f"({_reason(exc)}); no earlier bundle was there to replace") from None
        try:
            previous.rename(out)
        except OSError as again:
            raise PublicationFailed(
                f"Publication did not occur, and the original could not be put back: moving the new bundle into "
                f"place failed ({_reason(exc)}), then restoring the original failed ({_reason(again)}). The original "
                f"bundle is preserved, unchanged, at {previous}; nothing there was deleted. To restore it, make sure "
                f"nothing is at {out}, then rename that folder to {out}") from None
        raise PublicationFailed(f"Publication did not occur: the new bundle could not be moved into place "
                                f"({_reason(exc)}). The original bundle was restored unchanged at {out}") from None
    return previous


def publish(out: Path, work: Path) -> str | None:
    """Moves the finished folder `work` into place at `out` and removes the bundle it replaced.

    Returns None, or a warning when the replaced bundle could not be fully removed: the publication stands, and the
    warning names what is left. PublicationFailed means nothing new was published. A Ctrl-C held during the renames is
    delivered afterwards, with a note saying how publication ended."""
    failure = previous = None
    with ctrl_c_held() as held:
        try:
            previous = _move(out, work)
        except PublicationFailed as refused:
            failure = refused
    if failure is not None:
        held.deliver(f"Ctrl-C was held until publication ended. {failure}.")
        raise failure
    warning = None
    if previous is not None:
        try:
            shutil.rmtree(previous)
        except OSError as exc:  # The new bundle is already in place: report, never undo, a successful publication.
            warning = (f"Published, but the replaced bundle could not be fully removed ({_reason(exc)}). What is left "
                       f"is at {previous}: an old, possibly partial copy that nothing reads. Remove it when no process "
                       "is using it.")
    held.deliver(f"Ctrl-C was held until publication ended, and the publication was finished first: the new bundle is "
                 f"in place at {out}." + (f" {warning}" if warning else ""))
    return warning


def moved_aside(bundle: Path) -> list[tuple[Path, str | None, str | None]]:
    """Read-only: every moved-aside folder in `bundle`'s parent, by name, as (path, owner, time). The owner is the
    bundle folder name the folder's name records (None when it records none: an earlier version made it), the time
    the UTC time it records (None when it records none). Nothing here judges a folder's contents."""
    if not bundle.parent.is_dir():
        return []
    found = []
    for path in sorted(bundle.parent.glob(f"{PREVIOUS_PREFIX}*"), key=lambda path: path.name):
        if not path.is_dir():
            continue
        owned, unowned = OWNED.fullmatch(path.name), UNOWNED_TIMESTAMPED.match(path.name)
        if owned:
            found.append((path, owned.group(8), "{}-{}-{}T{}:{}:{}.{}Z".format(*owned.groups()[:7])))
        else:
            found.append((path, None, "{}-{}-{}T{}:{}:{}Z".format(*unowned.groups()) if unowned else None))
    return found


def owned_copies(bundle: Path) -> list[tuple[Path, str | None, str | None]]:
    """The moved-aside folders whose names record exactly `bundle`'s folder name as their owner. Read-only."""
    return [aside for aside in moved_aside(bundle) if aside[1] == bundle.name]


def recovery_report(bundle: Path, describe) -> tuple[bool, str | None]:
    """What lies beside a missing bundle, for the operator; reads only, and chooses nothing.

    Returns (whether any folder records this bundle as its owner, the report), and (False, None) when nothing beside
    it could be its copy. Ownership, order and integrity are kept apart:
    - ownership is what a folder's name records, matched exactly; folders of other bundles are only counted, and
      folders that record no owner are listed as of unknown origin, never as this bundle's;
    - order is the recorded time of the copies this bundle owns, newest first; copies recorded at the same time stay
      unordered, and the most recent one is named only when it alone has the latest time;
    - integrity is ``describe(folder)``: (whether its files verify, its runs, cases and methods and that verdict in
      words). It is reported for each copy and decides only how the most recent copy is described, never which copy
      is named: an older copy is never offered in place of a newer one."""
    found = moved_aside(bundle)
    owned = sorted((aside for aside in found if aside[1] == bundle.name), key=lambda aside: aside[2], reverse=True)
    unknown = [aside for aside in found if aside[1] is None]
    others = sorted({aside[1] for aside in found if aside[1] not in (None, bundle.name)})
    if not owned and not unknown:
        return False, None
    described = {path: describe(path) for path, _, _ in owned + unknown}
    parts = [f"No bundle is at {bundle}. Nothing has been restored, moved or deleted, and no folder is chosen for you."]
    if owned:
        parts.append(f"Copies recorded as moved aside from {bundle.name} are beside it, so a publication may have been "
                     "interrupted between its two renames. Newest recorded time first:")
        for number, (path, _, moved_at) in enumerate(owned, start=1):
            same = sum(aside[2] == moved_at for aside in owned) > 1
            parts.append(f"({number}) {path}: moved aside at {moved_at}"
                         f"{' (the same recorded time as another copy)' if same else ''}; {described[path][1]}.")
        latest = [aside for aside in owned if aside[2] == owned[0][2]]
        if len(latest) > 1:
            parts.append(f"{len(latest)} copies share the most recent recorded time, so which is newest is not known "
                         "and none is named as the most recent; compare their runs before deciding.")
        elif described[latest[0][0]][0]:
            parts.append(f"The most recent recorded copy is {latest[0][0]}. To restore it, make sure nothing is at "
                         f"{bundle}, then rename it to {bundle}.")
        else:
            parts.append(f"The most recent recorded copy is {latest[0][0]}, but its files do not verify: it is not safe "
                         "to restore as it is; inspect it before deciding.")
        if len(owned) > len(latest):
            parts.append("Older recorded copies are earlier states, not replacements: restoring one would drop what was "
                         "published after it.")
    else:
        parts.append(f"No moved-aside copy is recorded as {bundle.name}'s.")
    if unknown:
        listed = "; ".join(f"{path} ({'moved aside at ' + moved_at if moved_at else 'no recorded time'}; "
                           f"{described[path][1]})" for path, _, moved_at in unknown)
        parts.append(f"Folders whose names record no owner (made by an earlier version) are beside it too; which bundle "
                     f"each came from is not known, so none is presented as {bundle.name}'s: {listed}.")
    if others:
        parts.append(f"Moved-aside folders recorded as other bundles' ({', '.join(others)}) are unrelated and not listed.")
    parts.append("Folders named .market-context-<letters> are unfinished working copies, not originals.")
    if owned:
        parts.append("After restoring, run `python -m second_order.market_context check`.")
    return bool(owned), " ".join(parts)
