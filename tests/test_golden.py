"""Step 9 — End-to-end pipeline tests: Gerber → isolation → G-code.

These tests exercise the full headless CAM pipeline using the bundled
test.gbr fixture.  They are "golden" in the structural sense: they verify
that the output has the right shape (non-empty G-code, valid header tokens,
bounding-box sanity) rather than freezing exact byte output.

Pipeline: import_gerber → isolation → export_gcode
All three operations run via OperationRunner (topological walk).
"""
from __future__ import annotations

import pathlib
import re

import pytest

# Register built-in handlers as a side-effect of this import.
import flatcam_core.handlers  # noqa: F401

from flatcam_core import (
    ArtifactKind,
    Document,
    HeadlessAdapter,
    OperationKind,
    OperationNode,
    OperationResult,
    OperationRunner,
    Project,
    load_preprocessors,
)
from flatcam_core.compat import AppContextFacade, HEADLESS_DEFAULTS
from flatcam_core.handlers.export_gcode import handle_export_gcode
from flatcam_core.handlers.import_gerber import handle_import_gerber
from flatcam_core.handlers.isolation import handle_isolation
from flatcam_core.operations import OperationRequest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).parent.parent
TEST_GBR = REPO_ROOT / "assets" / "examples" / "files" / "test.gbr"


@pytest.fixture()
def test_gbr_path() -> pathlib.Path:
    if not TEST_GBR.exists():
        pytest.skip(f"Bundled Gerber fixture not found: {TEST_GBR}")
    return TEST_GBR


@pytest.fixture()
def ctx():
    return HeadlessAdapter(config=dict(HEADLESS_DEFAULTS))


@pytest.fixture()
def project(test_gbr_path):
    proj = Project(name="golden-test")
    doc = Document(
        name="test.gbr",
        source_path=str(test_gbr_path),
    )
    proj.add_document(doc)
    return proj


# ---------------------------------------------------------------------------
# load_preprocessors
# ---------------------------------------------------------------------------

def test_load_preprocessors_returns_dict():
    pp = load_preprocessors()
    assert isinstance(pp, dict)
    assert len(pp) > 0


def test_load_preprocessors_contains_default():
    pp = load_preprocessors()
    assert "default" in pp


def test_load_preprocessors_instances_have_lift_code():
    pp = load_preprocessors()
    assert hasattr(pp["default"], "lift_code")


# ---------------------------------------------------------------------------
# import_gerber handler (unit-level)
# ---------------------------------------------------------------------------

def test_import_gerber_returns_ok(test_gbr_path, ctx):
    proj = Project(name="t")
    doc = Document(name="test.gbr", source_path=str(test_gbr_path))
    proj.add_document(doc)

    req = OperationRequest(kind=OperationKind.IMPORT_GERBER, inputs=[doc.id])
    result = handle_import_gerber(req, proj, ctx)

    assert result.status == "ok"
    assert result.outputs


def test_import_gerber_artifact_has_solid_geometry(test_gbr_path, ctx):
    proj = Project(name="t")
    doc = Document(name="test.gbr", source_path=str(test_gbr_path))
    proj.add_document(doc)

    req = OperationRequest(kind=OperationKind.IMPORT_GERBER, inputs=[doc.id])
    result = handle_import_gerber(req, proj, ctx)

    art = proj.artifacts[result.outputs[0]]
    assert art.kind == ArtifactKind.GEOMETRY
    solid_geo = art.data["solid_geometry"]
    assert solid_geo is not None
    assert not (hasattr(solid_geo, "is_empty") and solid_geo.is_empty)


def test_import_gerber_missing_file_returns_error(ctx):
    proj = Project(name="t")
    doc = Document(name="missing.gbr", source_path="/nonexistent/path/missing.gbr")
    proj.add_document(doc)

    req = OperationRequest(kind=OperationKind.IMPORT_GERBER, inputs=[doc.id])
    result = handle_import_gerber(req, proj, ctx)

    assert result.status == "error"
    assert "not found" in result.error.lower()


def test_import_gerber_missing_document_returns_error(ctx):
    proj = Project(name="t")
    req = OperationRequest(kind=OperationKind.IMPORT_GERBER, inputs=["nonexistent-id"])
    result = handle_import_gerber(req, proj, ctx)
    assert result.status == "error"


# ---------------------------------------------------------------------------
# isolation handler (unit-level)
# ---------------------------------------------------------------------------

def test_isolation_returns_ok(test_gbr_path, ctx):
    proj = Project(name="t")
    doc = Document(name="test.gbr", source_path=str(test_gbr_path))
    proj.add_document(doc)

    import_req = OperationRequest(kind=OperationKind.IMPORT_GERBER, inputs=[doc.id])
    import_result = handle_import_gerber(import_req, proj, ctx)
    assert import_result.status == "ok"

    iso_req = OperationRequest(
        kind=OperationKind.ISOLATION,
        inputs=[import_result.outputs[0]],
        parameters={"tool_dia": 0.2, "passes": 1},
    )
    iso_result = handle_isolation(iso_req, proj, ctx)

    assert iso_result.status in ("ok", "partial")
    assert iso_result.outputs


def test_isolation_artifact_has_toolpath_kind(test_gbr_path, ctx):
    proj = Project(name="t")
    doc = Document(name="test.gbr", source_path=str(test_gbr_path))
    proj.add_document(doc)

    import_req = OperationRequest(kind=OperationKind.IMPORT_GERBER, inputs=[doc.id])
    import_result = handle_import_gerber(import_req, proj, ctx)

    iso_req = OperationRequest(
        kind=OperationKind.ISOLATION,
        inputs=[import_result.outputs[0]],
        parameters={"tool_dia": 0.2},
    )
    iso_result = handle_isolation(iso_req, proj, ctx)

    art = proj.artifacts[iso_result.outputs[0]]
    assert art.kind == ArtifactKind.TOOLPATH
    assert art.data["solid_geometry"]


def test_isolation_records_tool_dia_in_artifact(test_gbr_path, ctx):
    proj = Project(name="t")
    doc = Document(name="test.gbr", source_path=str(test_gbr_path))
    proj.add_document(doc)

    import_req = OperationRequest(kind=OperationKind.IMPORT_GERBER, inputs=[doc.id])
    import_result = handle_import_gerber(import_req, proj, ctx)

    iso_req = OperationRequest(
        kind=OperationKind.ISOLATION,
        inputs=[import_result.outputs[0]],
        parameters={"tool_dia": 0.3},
    )
    iso_result = handle_isolation(iso_req, proj, ctx)
    art = proj.artifacts[iso_result.outputs[0]]
    assert art.data["tool_dia"] == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# export_gcode handler (unit-level)
# ---------------------------------------------------------------------------

def test_export_gcode_returns_ok(test_gbr_path, ctx):
    proj = Project(name="t")
    doc = Document(name="test.gbr", source_path=str(test_gbr_path))
    proj.add_document(doc)

    import_req = OperationRequest(kind=OperationKind.IMPORT_GERBER, inputs=[doc.id])
    import_result = handle_import_gerber(import_req, proj, ctx)
    iso_req = OperationRequest(
        kind=OperationKind.ISOLATION,
        inputs=[import_result.outputs[0]],
        parameters={"tool_dia": 0.2, "passes": 1},
    )
    iso_result = handle_isolation(iso_req, proj, ctx)
    assert iso_result.status in ("ok", "partial")

    gcode_req = OperationRequest(
        kind=OperationKind.EXPORT_GCODE,
        inputs=[iso_result.outputs[0]],
        parameters={"z_cut": -0.1, "z_move": 2.0, "feedrate": 100.0},
    )
    gcode_result = handle_export_gcode(gcode_req, proj, ctx)

    assert gcode_result.status == "ok", gcode_result.error
    assert gcode_result.outputs


def test_export_gcode_artifact_is_gcode_kind(test_gbr_path, ctx):
    proj, iso_art_id = _run_through_isolation(test_gbr_path, ctx)

    gcode_req = OperationRequest(
        kind=OperationKind.EXPORT_GCODE,
        inputs=[iso_art_id],
        parameters={},
    )
    gcode_result = handle_export_gcode(gcode_req, proj, ctx)
    art = proj.artifacts[gcode_result.outputs[0]]
    assert art.kind == ArtifactKind.GCODE


def test_export_gcode_output_is_nonempty_string(test_gbr_path, ctx):
    proj, iso_art_id = _run_through_isolation(test_gbr_path, ctx)

    gcode_req = OperationRequest(
        kind=OperationKind.EXPORT_GCODE,
        inputs=[iso_art_id],
        parameters={},
    )
    result = handle_export_gcode(gcode_req, proj, ctx)
    gcode = proj.artifacts[result.outputs[0]].data["gcode"]
    assert isinstance(gcode, str) and len(gcode) > 0


def test_export_gcode_contains_unit_header(test_gbr_path, ctx):
    proj, iso_art_id = _run_through_isolation(test_gbr_path, ctx)

    gcode_req = OperationRequest(
        kind=OperationKind.EXPORT_GCODE,
        inputs=[iso_art_id],
        parameters={},
    )
    result = handle_export_gcode(gcode_req, proj, ctx)
    gcode = proj.artifacts[result.outputs[0]].data["gcode"]
    # G21 = metric, G20 = imperial
    assert re.search(r"\bG2[01]\b", gcode), "Expected unit selection G-code (G20 or G21)"


def test_export_gcode_contains_coordinates(test_gbr_path, ctx):
    proj, iso_art_id = _run_through_isolation(test_gbr_path, ctx)

    gcode_req = OperationRequest(
        kind=OperationKind.EXPORT_GCODE,
        inputs=[iso_art_id],
        parameters={},
    )
    result = handle_export_gcode(gcode_req, proj, ctx)
    gcode = proj.artifacts[result.outputs[0]].data["gcode"]
    # Must contain at least one XY move
    assert re.search(r"X-?\d+(\.\d+)?\s+Y-?\d+(\.\d+)?", gcode), (
        "Expected XY coordinate moves in G-code"
    )


def test_export_gcode_invalid_preprocessor_returns_error(test_gbr_path, ctx):
    proj, iso_art_id = _run_through_isolation(test_gbr_path, ctx)

    gcode_req = OperationRequest(
        kind=OperationKind.EXPORT_GCODE,
        inputs=[iso_art_id],
        parameters={"preprocessor": "nonexistent_pp_xyz"},
    )
    result = handle_export_gcode(gcode_req, proj, ctx)
    assert result.status == "error"
    assert "nonexistent_pp_xyz" in result.error


# ---------------------------------------------------------------------------
# Full pipeline via OperationRunner
# ---------------------------------------------------------------------------

def test_full_pipeline_via_runner(test_gbr_path):
    """End-to-end: OperationRunner drives import → isolation → export_gcode."""
    ctx = HeadlessAdapter(config=dict(HEADLESS_DEFAULTS))
    proj = Project(name="full-pipeline")

    doc = Document(name="test.gbr", source_path=str(test_gbr_path))
    doc_id = proj.add_document(doc)

    import_op = OperationNode(kind=OperationKind.IMPORT_GERBER, inputs=[doc_id])
    import_id = proj.add_operation(import_op)

    iso_op = OperationNode(
        kind=OperationKind.ISOLATION,
        inputs=[import_id],  # will be updated after import completes
        params={"tool_dia": 0.2, "passes": 1},
    )
    iso_id = proj.add_operation(iso_op)

    export_op = OperationNode(
        kind=OperationKind.EXPORT_GCODE,
        inputs=[iso_id],
        params={"z_cut": -0.1, "z_move": 2.0},
    )
    export_id = proj.add_operation(export_op)

    runner = OperationRunner(proj, ctx)
    runner.run_all()

    assert proj.operations[import_id].status == "done", "import_gerber should be done"
    assert proj.operations[iso_id].status in ("done",), (
        f"isolation status: {proj.operations[iso_id].status}"
    )
    assert proj.operations[export_id].status == "done", (
        f"export_gcode status: {proj.operations[export_id].status}"
    )

    # Verify the G-code artifact exists and is non-empty
    gcode_art_id = proj.operations[export_id].outputs[0]
    gcode_art = proj.artifacts[gcode_art_id]
    assert gcode_art.kind == ArtifactKind.GCODE
    assert gcode_art.data["gcode"]


def test_runner_stops_on_cancel(test_gbr_path):
    """Cancelling mid-run stops before export_gcode."""
    import threading

    ctx = HeadlessAdapter(config=dict(HEADLESS_DEFAULTS))
    proj = Project(name="cancel-test")

    doc = Document(name="test.gbr", source_path=str(test_gbr_path))
    doc_id = proj.add_document(doc)

    import_op = OperationNode(kind=OperationKind.IMPORT_GERBER, inputs=[doc_id])
    import_id = proj.add_operation(import_op)

    iso_op = OperationNode(
        kind=OperationKind.ISOLATION,
        inputs=[import_id],
        params={"tool_dia": 0.2},
    )
    iso_id = proj.add_operation(iso_op)

    export_op = OperationNode(
        kind=OperationKind.EXPORT_GCODE,
        inputs=[iso_id],
        params={},
    )
    export_id = proj.add_operation(export_op)

    # Cancel immediately so run_all aborts after the first ready batch
    ctx.cancel.set()

    runner = OperationRunner(proj, ctx)
    runner.run_all()

    # With cancel set, run_all returns immediately without executing any operation.
    assert proj.operations[import_id].status == "pending"
    assert proj.operations[iso_id].status == "pending"
    assert proj.operations[export_id].status == "pending"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_through_isolation(test_gbr_path, ctx):
    """Return (project, isolation_artifact_id) — convenience for gcode tests."""
    proj = Project(name="t")
    doc = Document(name="test.gbr", source_path=str(test_gbr_path))
    proj.add_document(doc)

    import_req = OperationRequest(kind=OperationKind.IMPORT_GERBER, inputs=[doc.id])
    import_result = handle_import_gerber(import_req, proj, ctx)

    iso_req = OperationRequest(
        kind=OperationKind.ISOLATION,
        inputs=[import_result.outputs[0]],
        parameters={"tool_dia": 0.2, "passes": 1},
    )
    iso_result = handle_isolation(iso_req, proj, ctx)
    return proj, iso_result.outputs[0]
