"""The raytrace subprocess guard returns a large result promptly.

2026-11-13, SIGMA: raytrace_2d traced 117 rays in 0.04 s, but the guard waited
for the child to exit before reading the queue.  The child's result pickled to
6.1 MB; the queue's feeder thread could not hand it over until someone read it,
so the child never exited and every trace hit the 120 s timeout and fell back
to geometry.  These workers stand in for the subprocess: module-level, so the
``spawn`` start method can import them.
"""

import os
import time

import pytest

from hamsci_dsp import raytrace as rt


def _big_result_worker(queue, fn_args):
    queue.put(("ok", b"x" * (6 * 1024 * 1024)))


def _dies_without_result_worker(queue, fn_args):
    os._exit(3)


def _hangs_worker(queue, fn_args):
    time.sleep(60)


def _error_worker(queue, fn_args):
    queue.put(("err", "boom"))


def test_large_result_returns_before_the_timeout():
    t0 = time.monotonic()
    out = rt._raytrace_with_timeout((), timeout_s=20, _target=_big_result_worker)
    assert len(out) == 6 * 1024 * 1024
    assert time.monotonic() - t0 < 15


def test_worker_that_dies_without_a_result_fails_fast():
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="without result"):
        rt._raytrace_with_timeout((), timeout_s=30, _target=_dies_without_result_worker)
    assert time.monotonic() - t0 < 15


def test_hung_worker_is_killed_at_the_timeout():
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        rt._raytrace_with_timeout((), timeout_s=2, _target=_hangs_worker)
    assert time.monotonic() - t0 < 15


def test_worker_error_is_raised():
    with pytest.raises(RuntimeError, match="boom"):
        rt._raytrace_with_timeout((), timeout_s=20, _target=_error_worker)


def test_worker_sends_only_the_ray_list(monkeypatch):
    """Nothing reads the ray paths or states, and they are most of the bytes."""
    monkeypatch.setattr(rt, "_pylap_raytrace_2d",
                        lambda *a: (["rays"], ["paths"], ["states"]))
    msgs = []

    class _Queue:
        def put(self, m):
            msgs.append(m)

    rt._raytrace_worker(_Queue(), ())
    assert msgs == [("ok", (["rays"], None, None))]
