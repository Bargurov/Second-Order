"""Execution locks for user analysis attempts: evidence of whether a worker can still send or record an attempt.

The worker that runs an attempt holds the attempt's exclusive lock from just before its send is recorded until its
outcome is settled. An administrator's resolution takes the same lock, so it can never overlap a live worker: while a
worker holds it, the attempt is in flight however old it is; once it is free, no worker of any thread or process is
running it. The operating system releases the lock when its process ends (a crash, a stop or a restart), so a free
lock after an interruption is evidence, not an assumption about timeouts.

The lock files hold no data. ``active`` only probes: it never creates a file, so reads write nothing.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import time
from typing import Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl

NAME = re.compile(r"[A-Za-z0-9._-]{1,120}")
WORKER_WAIT = 10.0  # Covers a concurrent probe or an administrator's resolution, each a moment long.
ADMIN_WAIT = 2.0
RETRY = 0.02


class Busy(Exception):
    """Another holder has the lock: a worker is running the attempt, or a resolution is being made."""


def _path(folder: Path, name: str) -> Path:
    if not NAME.fullmatch(name):
        raise ValueError("Unsafe lock name")
    return folder / f"{name}.lock"


def _try(handle: int) -> bool:
    try:
        if os.name == "nt":
            os.lseek(handle, 0, os.SEEK_SET)
            msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _release(handle: int) -> None:
    try:
        if os.name == "nt":
            os.lseek(handle, 0, os.SEEK_SET)
            msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)


@contextmanager
def hold(folder: Path, name: str, wait: float = 0.0) -> Iterator[None]:
    """Hold the named lock for the block, waiting up to ``wait`` seconds for a momentary holder; else raise Busy."""
    folder.mkdir(parents=True, exist_ok=True)
    handle = os.open(_path(folder, name), os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + wait
    while not _try(handle):
        if time.monotonic() >= deadline:
            os.close(handle)
            raise Busy(name)
        time.sleep(RETRY)
    try:
        yield
    finally:
        _release(handle)


def active(folder: Path, name: str) -> bool:
    """Whether a holder has the lock now. A lock file that was never created was never held."""
    try:
        handle = os.open(_path(folder, name), os.O_RDWR)
    except FileNotFoundError:
        return False
    if _try(handle):
        _release(handle)
        return False
    os.close(handle)
    return True
