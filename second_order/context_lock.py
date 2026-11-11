"""A non-blocking, cross-process lock for an explicit market-context bundle write.

The sidecar stays beside the bundle, outside the folder that publication replaces. Never unlink it on release:
another process may already have opened that same file. The OS releases the lock if its owner exits or crashes.
Reading a bundle does not use this helper or create a lock file.
"""
from contextlib import contextmanager
import os
from pathlib import Path


class BundleBusy(OSError):
    """Another writer holds this bundle's lock; the caller must refuse rather than wait or retry."""


@contextmanager
def bundle_write_lock(bundle: Path):
    target = bundle.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.with_name(f".{target.name}.lock").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise BundleBusy("Another market-context writer holds this bundle") from None
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise BundleBusy("Another market-context writer holds this bundle") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
