"""Smoke tests for headless (no QApplication) CAM operations.

These tests verify Step 5 of the headless decoupling plan:
camlib base classes can be instantiated and run under AppContextFacade
without any Qt event loop.

Tested path: Gerber.__new__ → set facade → __init__ → isolation_geometry
"""
import pytest
from shapely.geometry import box, MultiPolygon, Polygon

from flatcam_core import HeadlessAdapter
from flatcam_core.compat import AppContextFacade, HEADLESS_DEFAULTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_facade(extra: dict = None) -> AppContextFacade:
    ctx = HeadlessAdapter(config=dict(HEADLESS_DEFAULTS) | (extra or {}))
    return AppContextFacade(ctx)


def _make_gerber(facade: AppContextFacade = None):
    """Instantiate a Gerber object headless, bypassing the Qt MRO setup."""
    from appParsers.ParseGerber import Gerber
    if facade is None:
        facade = _make_facade()
    gerber = Gerber.__new__(Gerber)
    gerber.app = facade
    gerber.__init__()
    return gerber


def _make_excellon(facade: AppContextFacade = None):
    """Instantiate an Excellon object headless."""
    from appParsers.ParseExcellon import Excellon
    if facade is None:
        facade = _make_facade()
    exc = Excellon.__new__(Excellon)
    exc.app = facade
    exc.__init__()
    return exc


# ---------------------------------------------------------------------------
# AppContextFacade unit tests
# ---------------------------------------------------------------------------

def test_facade_log():
    import logging
    facade = _make_facade()
    assert isinstance(facade.log, logging.Logger)


def test_facade_abort_flag_false_by_default():
    facade = _make_facade()
    assert facade.abort_flag is False


def test_facade_abort_flag_reflects_cancel():
    import threading
    flag = threading.Event()
    ctx = HeadlessAdapter(cancel=flag)
    facade = AppContextFacade(ctx)
    assert not facade.abort_flag
    flag.set()
    assert facade.abort_flag


def test_facade_options_includes_defaults():
    facade = _make_facade()
    assert "gerber_circle_steps" in facade.options
    assert facade.options["gerber_circle_steps"] == 64


def test_facade_caller_config_overrides_defaults():
    facade = _make_facade({"gerber_circle_steps": 32})
    assert facade.options["gerber_circle_steps"] == 32


def test_facade_app_units_default():
    facade = _make_facade()
    assert facade.app_units == "mm"


def test_facade_app_units_override():
    facade = _make_facade({"units": "in"})
    assert facade.app_units == "in"


def test_facade_decimals():
    facade = _make_facade()
    assert facade.decimals == 4


def test_facade_inform_has_emit():
    facade = _make_facade()
    facade.inform.emit("[INFO] hello headless")  # must not raise


def test_facade_inform_no_echo_has_emit():
    facade = _make_facade()
    facade.inform_no_echo.emit("[INFO] silent message")  # must not raise


def test_facade_proc_container_update():
    facade = _make_facade()
    facade.proc_container.update_view_text("50%")  # must not raise


def test_facade_exc_areas_empty():
    facade = _make_facade()
    assert facade.exc_areas.exclusion_areas_storage == []
    assert facade.exc_areas.travel_coordinates(start_point=(0, 0), stop_point=(1, 1)) == []


def test_facade_use_3d_engine_true():
    # Must be True so Geometry.__init__ takes the VisPy branch
    # (avoids importing appGUI.PlotCanvasLegacy which pulls in Qt widgets).
    facade = _make_facade()
    assert facade.use_3d_engine is True


def test_facade_plotcanvas_noop():
    facade = _make_facade()
    coll = facade.plotcanvas.new_shape_collection(layers=1)
    coll.add(shape=None)  # must not raise


# ---------------------------------------------------------------------------
# Gerber headless instantiation
# ---------------------------------------------------------------------------

def test_gerber_instantiates_headless():
    gerber = _make_gerber()
    assert gerber is not None
    assert gerber.solid_geometry is not None


def test_gerber_steps_per_circle_from_config():
    facade = _make_facade({"gerber_circle_steps": 32})
    gerber = _make_gerber(facade)
    assert gerber.steps_per_circle == 32


def test_gerber_steps_per_circle_explicit():
    from appParsers.ParseGerber import Gerber
    facade = _make_facade()
    gerber = Gerber.__new__(Gerber)
    gerber.app = facade
    gerber.__init__(steps_per_circle=16)
    assert gerber.steps_per_circle == 16


def test_gerber_default_units_from_config():
    gerber = _make_gerber()
    # gerber_def_units default is 'MM'
    assert gerber.units == "MM"


# ---------------------------------------------------------------------------
# Gerber → isolation_geometry (the key Step-5 smoke test)
# ---------------------------------------------------------------------------

def test_isolation_geometry_returns_geometry():
    gerber = _make_gerber()
    gerber.solid_geometry = box(0, 0, 10, 10)
    result = gerber.isolation_geometry(offset=0.1, passes=0)
    assert result is not None
    assert result != "fail"


def test_isolation_geometry_expands_shape():
    gerber = _make_gerber()
    source = box(0, 0, 10, 10)
    gerber.solid_geometry = source
    result = gerber.isolation_geometry(offset=0.5, passes=0)
    # The isolation ring surrounds the source; its bounding box should be larger.
    if isinstance(result, list):
        from shapely.ops import unary_union
        result_geom = unary_union(result)
    else:
        result_geom = result
    assert result_geom.bounds[2] > source.bounds[2]


def test_isolation_geometry_not_cancelled():
    gerber = _make_gerber()
    gerber.solid_geometry = box(0, 0, 5, 5)
    result = gerber.isolation_geometry(offset=0.1, passes=0)
    assert result != "fail"
    assert not gerber.app.abort_flag


def test_isolation_geometry_cancel_raises():
    import threading
    from appCommon.Common import GracefulException
    flag = threading.Event()
    ctx = HeadlessAdapter(cancel=flag, config=dict(HEADLESS_DEFAULTS))
    facade = AppContextFacade(ctx)
    gerber = _make_gerber(facade)
    gerber.solid_geometry = box(0, 0, 10, 10)
    flag.set()  # cancel before the call
    with pytest.raises(GracefulException):
        gerber.isolation_geometry(offset=0.1, passes=0)


def test_isolation_geometry_zero_offset():
    gerber = _make_gerber()
    source = box(0, 0, 10, 10)
    gerber.solid_geometry = source
    # offset=0 returns the geometry unchanged
    result = gerber.isolation_geometry(offset=0, passes=0)
    assert result is not None


def test_isolation_exteriors_only():
    gerber = _make_gerber()
    gerber.solid_geometry = box(0, 0, 10, 10)
    result = gerber.isolation_geometry(offset=0.1, iso_type=0, passes=0)
    assert result is not None


# ---------------------------------------------------------------------------
# Excellon headless instantiation
# ---------------------------------------------------------------------------

def test_excellon_instantiates_headless():
    exc = _make_excellon()
    assert exc is not None


def test_excellon_has_tools_dict():
    exc = _make_excellon()
    assert isinstance(exc.tools, dict)
