"""Step 8 — Global-state + concurrency hardening tests.

Verifies three properties:
1. Cancel isolation  — cancelling one job never affects another job's cancel flag.
2. Config isolation  — per-request config snapshots are immutable and independent.
3. Output determinism — two concurrent isolation_geometry calls on the same input
   produce identical results with no shared mutable state.
4. MachineRegistry   — safe for concurrent reads after startup.
"""
import threading
from typing import Optional

import pytest
from shapely.geometry import box
from shapely.ops import unary_union

from flatcam_core import HeadlessAdapter
from flatcam_core.compat import AppContextFacade, HEADLESS_DEFAULTS
from flatcam_core.machine import MachineBackend, MachineRegistry, ToolpathParams


# ---------------------------------------------------------------------------
# Helpers (mirror smoke-test helpers so this file is self-contained)
# ---------------------------------------------------------------------------

def _make_ctx(
    extra: dict = None,
    cancel: Optional[threading.Event] = None,
) -> HeadlessAdapter:
    return HeadlessAdapter(
        config=dict(HEADLESS_DEFAULTS) | (extra or {}),
        cancel=cancel,
    )


def _make_facade(
    extra: dict = None,
    cancel: Optional[threading.Event] = None,
) -> AppContextFacade:
    return AppContextFacade(_make_ctx(extra=extra, cancel=cancel))


def _make_gerber(facade: AppContextFacade = None):
    from appParsers.ParseGerber import Gerber
    if facade is None:
        facade = _make_facade()
    gerber = Gerber.__new__(Gerber)
    gerber.app = facade
    gerber.__init__()
    return gerber


class _EchoBackend(MachineBackend):
    def start_code(self, p): return "START"
    def lift_code(self, p): return "LIFT"
    def down_code(self, p): return "DOWN"
    def toolchange_code(self, p): return "TC"
    def up_to_zero_code(self, p): return "UP0"
    def rapid_code(self, p): return "G00"
    def linear_code(self, p): return "G01"
    def end_code(self, p): return "END"
    def feedrate_code(self, p): return "F"
    def spindle_code(self, p): return "M03"
    def spindle_stop_code(self, p): return "M05"


# ---------------------------------------------------------------------------
# Cancel isolation
# ---------------------------------------------------------------------------

def test_headless_adapter_creates_independent_cancel_events():
    """Two adapters created without an explicit cancel flag get separate events."""
    ctx_a = _make_ctx()
    ctx_b = _make_ctx()
    assert ctx_a.cancel is not ctx_b.cancel
    ctx_a.cancel.set()
    assert not ctx_b.cancel.is_set()


def test_explicit_cancel_flag_is_per_adapter():
    """Two adapters with different explicit flags are fully independent."""
    flag_a = threading.Event()
    flag_b = threading.Event()
    facade_a = _make_facade(cancel=flag_a)
    facade_b = _make_facade(cancel=flag_b)
    flag_a.set()
    assert facade_a.abort_flag is True
    assert facade_b.abort_flag is False


def test_cancel_does_not_bleed_to_fresh_adapter():
    """Cancelling one adapter leaves a separately created adapter clean."""
    from appCommon.Common import GracefulException

    flag = threading.Event()
    facade = _make_facade(cancel=flag)
    gerber = _make_gerber(facade)
    gerber.solid_geometry = box(0, 0, 5, 5)
    flag.set()
    with pytest.raises(GracefulException):
        gerber.isolation_geometry(offset=0.1, passes=0)

    # Completely new adapter — unaffected by the cancelled one above
    fresh_facade = _make_facade()
    fresh_gerber = _make_gerber(fresh_facade)
    fresh_gerber.solid_geometry = box(0, 0, 5, 5)
    result = fresh_gerber.isolation_geometry(offset=0.1, passes=0)
    assert result is not None and result != "fail"


def test_concurrent_cancel_isolation():
    """Cancelling job A in a parallel thread does not affect job B.

    Both jobs start at the same time (Barrier).  Job A's cancel flag is set
    before the threads launch; Job B's flag is never set.  Expected outcome:
    Job A raises GracefulException, Job B completes normally.
    """
    from appCommon.Common import GracefulException

    flag_a = threading.Event()
    flag_a.set()  # pre-cancel job A

    facade_a = _make_facade(cancel=flag_a)
    facade_b = _make_facade()  # own fresh Event, not cancelled

    gerber_a = _make_gerber(facade_a)
    gerber_b = _make_gerber(facade_b)
    source = box(0, 0, 10, 10)
    gerber_a.solid_geometry = source
    gerber_b.solid_geometry = source

    exc_a: list = [None]
    result_b: list = [None]
    exc_b: list = [None]
    barrier = threading.Barrier(2)

    def run_a():
        barrier.wait()
        try:
            gerber_a.isolation_geometry(offset=0.1, passes=0)
        except GracefulException as e:
            exc_a[0] = e
        except Exception as e:
            exc_a[0] = e

    def run_b():
        barrier.wait()
        try:
            result_b[0] = gerber_b.isolation_geometry(offset=0.1, passes=0)
        except Exception as e:
            exc_b[0] = e

    t_a = threading.Thread(target=run_a)
    t_b = threading.Thread(target=run_b)
    t_a.start()
    t_b.start()
    t_a.join(timeout=30)
    t_b.join(timeout=30)

    assert isinstance(exc_a[0], GracefulException), (
        f"Job A should have raised GracefulException, got: {exc_a[0]}"
    )
    assert exc_b[0] is None, f"Job B raised unexpectedly: {exc_b[0]}"
    assert result_b[0] is not None, "Job B should have produced a result"


# ---------------------------------------------------------------------------
# Config isolation
# ---------------------------------------------------------------------------

def test_facade_options_is_immutable():
    """AppContextFacade.options is a MappingProxyType — writes raise TypeError."""
    facade = _make_facade()
    with pytest.raises(TypeError):
        facade.options["injected_key"] = 42  # type: ignore[index]


def test_headless_adapter_config_is_immutable():
    """HeadlessAdapter.config is a MappingProxyType — writes raise TypeError."""
    ctx = _make_ctx()
    with pytest.raises(TypeError):
        ctx.config["injected_key"] = 42  # type: ignore[index]


def test_config_overrides_do_not_mutate_headless_defaults():
    """Building a facade with overrides does not modify the HEADLESS_DEFAULTS dict."""
    original = dict(HEADLESS_DEFAULTS)
    _make_facade({"gerber_circle_steps": 999, "new_custom_key": True})
    assert dict(HEADLESS_DEFAULTS) == original


def test_two_facades_have_independent_options():
    """Two AppContextFacade instances built from different configs are isolated."""
    facade_a = _make_facade({"gerber_circle_steps": 16})
    facade_b = _make_facade({"gerber_circle_steps": 128})
    assert facade_a.options["gerber_circle_steps"] == 16
    assert facade_b.options["gerber_circle_steps"] == 128
    assert facade_a.options is not facade_b.options


def test_concurrent_gerber_instances_have_independent_steps():
    """Two Gerber objects created in parallel threads each see their own config."""
    steps_seen: dict = {}
    errors: list = []
    barrier = threading.Barrier(2)

    def make_and_record(key, steps):
        facade = _make_facade({"gerber_circle_steps": steps})
        barrier.wait()
        try:
            gerber = _make_gerber(facade)
            steps_seen[key] = gerber.steps_per_circle
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=make_and_record, args=("a", 16))
    t2 = threading.Thread(target=make_and_record, args=("b", 64))
    t1.start(); t2.start()
    t1.join(timeout=15); t2.join(timeout=15)

    assert not errors, f"Threads raised: {errors}"
    assert steps_seen.get("a") == 16
    assert steps_seen.get("b") == 64


def test_concurrent_adapters_with_different_units():
    """Concurrent adapters built with different unit configs report correct units."""
    results: dict = {}
    barrier = threading.Barrier(2)

    def run(key, units):
        ctx = _make_ctx(extra={"units": units})
        facade = AppContextFacade(ctx)
        barrier.wait()
        results[key] = facade.options["units"]

    t1 = threading.Thread(target=run, args=("a", "mm"))
    t2 = threading.Thread(target=run, args=("b", "in"))
    t1.start(); t2.start()
    t1.join(timeout=5); t2.join(timeout=5)

    assert results.get("a") == "mm"
    assert results.get("b") == "in"


# ---------------------------------------------------------------------------
# Output determinism under concurrency
# ---------------------------------------------------------------------------

def test_concurrent_isolation_produces_identical_results():
    """Two isolation_geometry calls on the same input in parallel return the same bounds."""
    source = box(0, 0, 10, 10)
    results: dict = {}
    errors: dict = {}
    barrier = threading.Barrier(2)

    def run_isolation(key):
        facade = _make_facade()
        gerber = _make_gerber(facade)
        gerber.solid_geometry = source
        barrier.wait()
        try:
            geom = gerber.isolation_geometry(offset=0.2, passes=0)
            if isinstance(geom, list):
                geom = unary_union(geom)
            results[key] = geom.bounds
        except Exception as e:
            errors[key] = e

    t1 = threading.Thread(target=run_isolation, args=("a",))
    t2 = threading.Thread(target=run_isolation, args=("b",))
    t1.start(); t2.start()
    t1.join(timeout=30); t2.join(timeout=30)

    assert not errors, f"Thread errors: {errors}"
    assert "a" in results and "b" in results, "Both jobs must complete"
    # Shapely geometry is deterministic for identical inputs
    assert results["a"] == pytest.approx(results["b"], abs=1e-9)


def test_three_concurrent_isolation_jobs_all_complete():
    """Three simultaneous isolation jobs complete without interfering with each other."""
    source = box(0, 0, 5, 5)
    results: list = [None] * 3
    errors: list = [None] * 3
    barrier = threading.Barrier(3)

    def run(idx):
        facade = _make_facade()
        gerber = _make_gerber(facade)
        gerber.solid_geometry = source
        barrier.wait()
        try:
            results[idx] = gerber.isolation_geometry(offset=0.1, passes=0)
        except Exception as e:
            errors[idx] = e

    threads = [threading.Thread(target=run, args=(i,)) for i in range(3)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=30)

    for i in range(3):
        assert errors[i] is None, f"Thread {i} raised: {errors[i]}"
        assert results[i] is not None, f"Thread {i} returned None"


# ---------------------------------------------------------------------------
# MachineRegistry thread-safety
# ---------------------------------------------------------------------------

def test_machine_registry_reads_are_thread_safe():
    """20 threads reading from a populated MachineRegistry cause no errors."""
    reg = MachineRegistry()
    for i in range(10):
        reg.register(f"backend_{i}", _EchoBackend())

    errors: list = []
    read_results: list = [None] * 20
    barrier = threading.Barrier(20)

    def read(idx):
        name = f"backend_{idx % 10}"
        barrier.wait()
        try:
            read_results[idx] = reg[name]
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=read, args=(i,)) for i in range(20)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=10)

    assert not errors, f"Registry reads raised: {errors}"
    assert all(isinstance(r, _EchoBackend) for r in read_results)


def test_machine_registry_contains_check_is_thread_safe():
    """10 threads checking __contains__ simultaneously see consistent results."""
    reg = MachineRegistry()
    reg.register("echo", _EchoBackend())
    errors: list = []
    barrier = threading.Barrier(10)

    def check(idx):
        barrier.wait()
        try:
            assert "echo" in reg
            assert "nope" not in reg
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=check, args=(i,)) for i in range(10)]
    for t in threads: t.start()
    for t in threads: t.join(timeout=10)

    assert not errors, f"Threads raised: {errors}"
