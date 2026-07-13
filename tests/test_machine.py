"""Tests for flatcam_core.machine — MachineBackend Step 7 of the decoupling plan."""
import pytest

from flatcam_core.machine import (
    MachineBackend,
    MachineRegistry,
    PreProcAdapter,
    ToolpathParams,
    load_machine_registry,
)


# ---------------------------------------------------------------------------
# Minimal concrete MachineBackend for testing the ABC
# ---------------------------------------------------------------------------

class _EchoBackend(MachineBackend):
    """Returns method-name strings so tests can assert routing."""

    def start_code(self, p): return f"START units={p.units}"
    def lift_code(self, p): return f"LIFT z={p.z_move}"
    def down_code(self, p): return f"DOWN z={p.z_cut}"
    def toolchange_code(self, p): return f"TC tool={p.tool}"
    def up_to_zero_code(self, p): return "UP0"
    def rapid_code(self, p): return f"G00 {self.position_code(p)}"
    def linear_code(self, p): return f"G01 {self.position_code(p)}"
    def end_code(self, p): return f"END z={p.z_end}"
    def feedrate_code(self, p): return f"F{p.feedrate}"
    def spindle_code(self, p): return f"M03 S{p.spindlespeed}"
    def spindle_stop_code(self, p): return "M05"


# ---------------------------------------------------------------------------
# ToolpathParams
# ---------------------------------------------------------------------------

def test_toolpath_params_defaults():
    p = ToolpathParams()
    assert p.x == 0.0
    assert p.y == 0.0
    assert p.z_cut == -0.1
    assert p.z_move == 2.0
    assert p.units == "MM"
    assert p.coords_decimals == 4
    assert p.startz is None
    assert p.spindlespeed is None
    assert p.extra == {}


def test_toolpath_params_custom_values():
    p = ToolpathParams(x=10.5, y=-3.2, z_cut=-0.5, feedrate=200.0, units="IN")
    assert p.x == 10.5
    assert p.y == -3.2
    assert p.z_cut == -0.5
    assert p.feedrate == 200.0
    assert p.units == "IN"


def test_toolpath_params_obj_options_default():
    p = ToolpathParams()
    assert p.obj_options["type"] == "Geometry"
    assert "xmin" in p.obj_options


def test_toolpath_params_extra_dict():
    p = ToolpathParams(extra={"laser_power": 80})
    assert p.extra["laser_power"] == 80


def test_toolpath_params_to_attrdict():
    p = ToolpathParams(x=5.0, y=3.0, feedrate=150.0, extra={"custom_key": "val"})
    d = p.to_attrdict()
    assert d.x == 5.0
    assert d.feedrate == 150.0
    assert d["custom_key"] == "val"  # extra merged in


def test_toolpath_params_to_attrdict_supports_dot_and_bracket():
    p = ToolpathParams(z_cut=-0.2)
    d = p.to_attrdict()
    assert d.z_cut == d["z_cut"] == -0.2


# ---------------------------------------------------------------------------
# MachineBackend — concrete defaults
# ---------------------------------------------------------------------------

def test_startz_code_none():
    b = _EchoBackend()
    p = ToolpathParams(startz=None)
    assert b.startz_code(p) == ""


def test_startz_code_set():
    b = _EchoBackend()
    p = ToolpathParams(startz=5.0, coords_decimals=2)
    result = b.startz_code(p)
    assert "G00 Z" in result
    assert "5.00" in result


def test_dwell_code_enabled():
    b = _EchoBackend()
    p = ToolpathParams(dwell=True, dwelltime=500)
    assert "G4 P500" in b.dwell_code(p)


def test_dwell_code_disabled():
    b = _EchoBackend()
    p = ToolpathParams(dwell=False)
    assert b.dwell_code(p) == ""


def test_dwell_code_zero_dwelltime():
    b = _EchoBackend()
    p = ToolpathParams(dwell=True, dwelltime=0)
    assert b.dwell_code(p) == ""


# ---------------------------------------------------------------------------
# MachineBackend.position_code — bed-skew correction
# ---------------------------------------------------------------------------

def test_position_code_no_skew_no_offset():
    b = _EchoBackend()
    p = ToolpathParams(x=5.0, y=3.0, coords_decimals=4)
    result = b.position_code(p)
    assert "X5.0000" in result
    assert "Y3.0000" in result


def test_position_code_with_offset():
    b = _EchoBackend()
    p = ToolpathParams(x=5.0, y=3.0, _bed_offset_x=1.0, _bed_offset_y=0.5, coords_decimals=4)
    result = b.position_code(p)
    assert "X6.0000" in result
    assert "Y3.5000" in result


def test_position_code_x_skew():
    b = _EchoBackend()
    # x_fin = (x + offset_x) + (y / limit_y) * skew_x
    # = (0 + 0) + (10.0 / 100.0) * 5.0 = 0.5
    p = ToolpathParams(
        x=0.0, y=10.0,
        _bed_skew_x=5.0, _bed_limit_y=100.0,
        _bed_offset_x=0.0, _bed_offset_y=0.0,
        coords_decimals=4,
    )
    result = b.position_code(p)
    assert "X0.5000" in result


def test_position_code_y_skew():
    b = _EchoBackend()
    # y_fin = (y + offset_y) + (x / limit_x) * skew_y
    # = (0 + 0) + (10.0 / 100.0) * 2.0 = 0.2
    p = ToolpathParams(
        x=10.0, y=0.0,
        _bed_skew_y=2.0, _bed_limit_x=100.0,
        _bed_offset_x=0.0, _bed_offset_y=0.0,
        coords_decimals=4,
    )
    result = b.position_code(p)
    assert "Y0.2000" in result


def test_rapid_code_includes_position():
    b = _EchoBackend()
    p = ToolpathParams(x=1.0, y=2.0, coords_decimals=2)
    result = b.rapid_code(p)
    assert "G00" in result
    assert "X1.00" in result


def test_linear_code_includes_position():
    b = _EchoBackend()
    p = ToolpathParams(x=3.0, y=4.0, coords_decimals=2)
    result = b.linear_code(p)
    assert "G01" in result
    assert "Y4.00" in result


# ---------------------------------------------------------------------------
# MachineRegistry
# ---------------------------------------------------------------------------

def test_registry_register_and_get():
    reg = MachineRegistry()
    b = _EchoBackend()
    reg.register("echo", b)
    assert reg.get("echo") is b


def test_registry_getitem():
    reg = MachineRegistry()
    b = _EchoBackend()
    reg.register("echo", b)
    assert reg["echo"] is b


def test_registry_missing_raises_key_error():
    reg = MachineRegistry()
    with pytest.raises(KeyError, match="missing"):
        reg.get("missing")


def test_registry_missing_getitem_raises():
    reg = MachineRegistry()
    with pytest.raises(KeyError):
        _ = reg["missing"]


def test_registry_contains():
    reg = MachineRegistry()
    reg.register("echo", _EchoBackend())
    assert "echo" in reg
    assert "nope" not in reg


def test_registry_names_sorted():
    reg = MachineRegistry()
    reg.register("zzz", _EchoBackend())
    reg.register("aaa", _EchoBackend())
    assert reg.names() == ["aaa", "zzz"]


def test_registry_len():
    reg = MachineRegistry()
    reg.register("a", _EchoBackend())
    reg.register("b", _EchoBackend())
    assert len(reg) == 2


def test_registry_items():
    reg = MachineRegistry()
    b = _EchoBackend()
    reg.register("echo", b)
    assert ("echo", b) in list(reg.items())


# ---------------------------------------------------------------------------
# PreProcAdapter — wraps a legacy PreProc-like object
# ---------------------------------------------------------------------------

class _MockPreProc:
    """Minimal mock that mimics a legacy PreProc."""
    include_header = True

    def lift_code(self, p): return f"MOCK_LIFT {p.z_move}"
    def down_code(self, p): return f"MOCK_DOWN {p.z_cut}"
    def start_code(self, p): return "MOCK_START"
    def toolchange_code(self, p): return "MOCK_TC"
    def up_to_zero_code(self, p): return "MOCK_UP0"
    def rapid_code(self, p): return "MOCK_G00"
    def linear_code(self, p): return "MOCK_G01"
    def end_code(self, p): return "MOCK_END"
    def feedrate_code(self, p): return "MOCK_F"
    def spindle_code(self, p): return "MOCK_M03"
    def spindle_stop_code(self, p): return "MOCK_M05"
    def startz_code(self, p): return "MOCK_STARTZ"
    def dwell_code(self, p): return "MOCK_DWELL"
    def position_code(self, p): return "MOCK_XY"


def test_preproc_adapter_delegates():
    adapter = PreProcAdapter(_MockPreProc())
    p = ToolpathParams()
    assert adapter.start_code(p) == "MOCK_START"
    assert adapter.lift_code(p) == f"MOCK_LIFT {p.z_move}"
    assert adapter.spindle_stop_code(p) == "MOCK_M05"


def test_preproc_adapter_include_header():
    class NoHeader:
        include_header = False
        # stub all other methods
        def start_code(self, p): return ""
        def lift_code(self, p): return ""
        def down_code(self, p): return ""
        def toolchange_code(self, p): return ""
        def up_to_zero_code(self, p): return ""
        def rapid_code(self, p): return ""
        def linear_code(self, p): return ""
        def end_code(self, p): return ""
        def feedrate_code(self, p): return ""
        def spindle_code(self, p): return ""
        def spindle_stop_code(self, p): return ""

    adapter = PreProcAdapter(NoHeader())
    assert adapter.include_header is False


def test_preproc_adapter_missing_method_returns_empty():
    class Partial:
        include_header = True
        def start_code(self, p): return "ok"
        # lift_code deliberately missing

    adapter = PreProcAdapter(Partial())
    # All abstract methods need stubs — but PreProcAdapter._call handles missing ones
    p = ToolpathParams()
    result = adapter.lift_code(p)
    assert result == ""


def test_preproc_adapter_raising_method_propagates_error():
    class Buggy:
        include_header = True
        def lift_code(self, p): raise ValueError("oops")
        def start_code(self, p): return ""
        def down_code(self, p): return ""
        def toolchange_code(self, p): return ""
        def up_to_zero_code(self, p): return ""
        def rapid_code(self, p): return ""
        def linear_code(self, p): return ""
        def end_code(self, p): return ""
        def feedrate_code(self, p): return ""
        def spindle_code(self, p): return ""
        def spindle_stop_code(self, p): return ""

    adapter = PreProcAdapter(Buggy())
    with pytest.raises(RuntimeError, match=r"Buggy.*lift_code") as exc_info:
        adapter.lift_code(ToolpathParams())
    assert isinstance(exc_info.value.__cause__, ValueError)


def test_preproc_adapter_passes_extra_fields():
    received = {}

    class Inspector:
        include_header = True
        def lift_code(self, p):
            received["laser_power"] = p.get("laser_power")
            return "ok"
        def start_code(self, p): return ""
        def down_code(self, p): return ""
        def toolchange_code(self, p): return ""
        def up_to_zero_code(self, p): return ""
        def rapid_code(self, p): return ""
        def linear_code(self, p): return ""
        def end_code(self, p): return ""
        def feedrate_code(self, p): return ""
        def spindle_code(self, p): return ""
        def spindle_stop_code(self, p): return ""

    adapter = PreProcAdapter(Inspector())
    p = ToolpathParams(extra={"laser_power": 90})
    adapter.lift_code(p)
    assert received["laser_power"] == 90


# ---------------------------------------------------------------------------
# load_machine_registry — integration (loads real bundled preprocessors)
# ---------------------------------------------------------------------------

def test_load_machine_registry_returns_registry():
    reg = load_machine_registry()
    assert isinstance(reg, MachineRegistry)


def test_load_machine_registry_contains_default():
    reg = load_machine_registry()
    assert "default" in reg


def test_load_machine_registry_default_is_adapter():
    reg = load_machine_registry()
    assert isinstance(reg["default"], PreProcAdapter)


def test_load_machine_registry_covers_common_preprocessors():
    reg = load_machine_registry()
    for name in ("default", "GRBL_11", "Marlin"):
        assert name in reg, f"Expected '{name}' in registry"


def test_load_machine_registry_lift_code_works():
    reg = load_machine_registry()
    backend = reg["default"]
    p = ToolpathParams(z_move=2.0, coords_decimals=4)
    result = backend.lift_code(p)
    assert "G00" in result
    assert "Z" in result


def test_load_machine_registry_spindle_stop():
    reg = load_machine_registry()
    result = reg["default"].spindle_stop_code(ToolpathParams())
    assert "M05" in result or "M5" in result
