# SPDX-License-Identifier: MIT

"""Small cross-process file lock used by qualification accounting artifacts."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator


def _lock_windows(handle: BinaryIO, deadline: float) -> None:
    import msvcrt

    while True:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "timed out acquiring qualification artifact lock"
                ) from None
            time.sleep(0.025)


def _unlock_windows(handle: BinaryIO) -> None:
    import msvcrt

    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def exclusive_path_lock(target: Path, timeout_s: float = 30.0) -> Iterator[None]:
    """Serialize writers to *target* across threads and processes.

    The persistent ``.lock`` sidecar contains one zero byte and no experiment
    data. Lock acquisition is bounded so accounting fails closed rather than
    hanging forever after an operating-system failure.
    """

    if timeout_s <= 0:
        raise ValueError("lock timeout must be positive")
    lock_path = target.with_suffix(target.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + timeout_s
        if os.name == "nt":
            _lock_windows(handle, deadline)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "timed out acquiring qualification artifact lock"
                        ) from None
                    time.sleep(0.025)
        try:
            yield
        finally:
            if os.name == "nt":
                _unlock_windows(handle)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
