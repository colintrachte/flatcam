from flatcam_core import (
    REQUIRED_PARAMS,
    OperationKind,
    OperationRequest,
    OperationResult,
)


def test_operation_kind_values():
    assert OperationKind.ISOLATION.value == "isolation"
    assert OperationKind.DRILL.value == "drill"
    assert OperationKind.CUTOUT.value == "cutout"
    assert OperationKind.IMPORT_GERBER.value == "import_gerber"
    assert OperationKind.IMPORT_EXCELLON.value == "import_excellon"
    assert OperationKind.EXPORT_GCODE.value == "export_gcode"


def test_operation_kind_is_str():
    # OperationKind(str, Enum) — value is usable as a plain string.
    assert OperationKind.ISOLATION == "isolation"


def test_operation_request_defaults():
    req = OperationRequest(kind=OperationKind.ISOLATION)
    assert req.inputs == []
    assert req.parameters == {}
    assert req.tool_id is None
    assert req.machine_profile is None
    assert req.material_profile is None


def test_operation_request_with_values():
    req = OperationRequest(
        kind=OperationKind.DRILL,
        inputs=["doc-1"],
        parameters={"tool_dia": 0.8},
        tool_id="tool-42",
    )
    assert req.inputs == ["doc-1"]
    assert req.parameters["tool_dia"] == 0.8
    assert req.tool_id == "tool-42"


def test_operation_result_defaults():
    res = OperationResult(status="ok")
    assert res.outputs == []
    assert res.warnings == []
    assert res.events == []
    assert res.timings == {}
    assert res.metrics == {}
    assert res.error is None


def test_operation_result_error():
    res = OperationResult(status="error", error="something failed")
    assert res.status == "error"
    assert res.error == "something failed"


def test_required_params_isolation():
    assert "tool_dia" in REQUIRED_PARAMS[OperationKind.ISOLATION.value]


def test_required_params_import_gerber_empty():
    assert REQUIRED_PARAMS[OperationKind.IMPORT_GERBER.value] == []


def test_required_params_import_excellon_empty():
    assert REQUIRED_PARAMS[OperationKind.IMPORT_EXCELLON.value] == []


def test_required_params_export_gcode_empty():
    assert REQUIRED_PARAMS[OperationKind.EXPORT_GCODE.value] == []


def test_required_params_covers_all_kinds():
    for kind in OperationKind:
        assert kind.value in REQUIRED_PARAMS, f"REQUIRED_PARAMS missing '{kind.value}'"
