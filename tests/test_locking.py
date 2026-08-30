import multiprocessing
import time

import pytest

from mathaudit.locking import exclusive_path_lock


def _hold_lock(target, ready):
    with exclusive_path_lock(target, timeout_s=2):
        ready.set()
        time.sleep(0.4)


def test_cross_process_lock_is_exclusive_and_bounded(tmp_path):
    target = tmp_path / "ledger.json"
    ready = multiprocessing.Event()
    process = multiprocessing.Process(target=_hold_lock, args=(target, ready))
    process.start()
    assert ready.wait(timeout=2)
    with pytest.raises(TimeoutError, match="timed out"):
        with exclusive_path_lock(target, timeout_s=0.1):
            pass
    process.join(timeout=3)
    assert process.exitcode == 0
    with exclusive_path_lock(target, timeout_s=1):
        pass
    assert target.with_suffix(".json.lock").read_bytes() == b"\0"
