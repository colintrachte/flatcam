import logging
import threading

import pytest

from flatcam_core import Event, HeadlessAdapter


def test_event_fields():
    e = Event(type="progress", source="isolation", level="info", message="50%", percent=50)
    assert e.type == "progress"
    assert e.source == "isolation"
    assert e.percent == 50
    assert e.data == {}


def test_event_percent_optional():
    e = Event(type="info", source="", level="info", message="done")
    assert e.percent is None


def test_headless_log_is_logger():
    ctx = HeadlessAdapter(logger_name="flatcam.test")
    assert isinstance(ctx.log, logging.Logger)
    assert ctx.log.name == "flatcam.test"


def test_headless_cancel_starts_unset():
    ctx = HeadlessAdapter()
    assert isinstance(ctx.cancel, threading.Event)
    assert not ctx.cancel.is_set()


def test_headless_cancel_isolation():
    ctx_a = HeadlessAdapter()
    ctx_b = HeadlessAdapter()
    ctx_a.cancel.set()
    assert not ctx_b.cancel.is_set()


def test_headless_config_values():
    ctx = HeadlessAdapter(config={"units": "mm", "tool_dia": 0.1})
    assert ctx.config["units"] == "mm"
    assert ctx.config["tool_dia"] == 0.1


def test_headless_config_is_read_only():
    ctx = HeadlessAdapter(config={"x": 1})
    with pytest.raises(TypeError):
        ctx.config["x"] = 2


def test_headless_config_empty_by_default():
    ctx = HeadlessAdapter()
    assert dict(ctx.config) == {}


def test_headless_emit_does_not_raise():
    ctx = HeadlessAdapter()
    ctx.emit(Event(type="info", source="test", level="info", message="hello"))


def test_headless_process_events_noop():
    ctx = HeadlessAdapter()
    ctx.process_events()  # must not raise


def test_headless_get_preprocessors_empty_by_default():
    ctx = HeadlessAdapter()
    assert ctx.get_preprocessors() == {}


def test_headless_get_preprocessors_returns_registry():
    pp = {"grbl": object()}
    ctx = HeadlessAdapter(preprocessors=pp)
    assert ctx.get_preprocessors() is pp


def test_headless_external_cancel_event():
    flag = threading.Event()
    ctx = HeadlessAdapter(cancel=flag)
    assert ctx.cancel is flag


# --- inform() helper ---

@pytest.mark.parametrize("msg,expected_level", [
    ("[ERROR] something went wrong", "error"),
    ("[WARNING] watch out",          "warning"),
    ("[SUCCESS] all done",           "info"),
    ("plain informational text",     "info"),
])
def test_inform_level_detection(msg, expected_level):
    collected: list = []

    class SpyAdapter(HeadlessAdapter):
        def emit(self, event: Event) -> None:
            collected.append(event)

    ctx = SpyAdapter()
    ctx.inform(msg, source="test")
    assert len(collected) == 1
    assert collected[0].level == expected_level
    assert collected[0].message == msg


# --- progress() helper ---

def test_progress_emits_progress_event():
    collected: list = []

    class SpyAdapter(HeadlessAdapter):
        def emit(self, event: Event) -> None:
            collected.append(event)

    ctx = SpyAdapter()
    ctx.progress("computing", percent=42.0, source="iso")
    assert len(collected) == 1
    e = collected[0]
    assert e.type == "progress"
    assert e.percent == 42.0
    assert e.source == "iso"
    assert e.message == "computing"
