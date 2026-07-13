import threading

import pytest

from flatcam_core import (
    Artifact,
    ArtifactKind,
    Document,
    HeadlessAdapter,
    OperationKind,
    OperationNode,
    OperationRequest,
    OperationResult,
    OperationRunner,
    Project,
    get_handler,
    handler,
    register_handler,
)


# All tests here use clean_handlers to isolate the module-level registry.

def _ok_handler(req, project, ctx):
    return OperationResult(status="ok")


def _ok_handler_with_artifact(req, project, ctx):
    art = Artifact(
        name="output",
        kind=ArtifactKind.TOOLPATH,
        producer_op=req.operation_id,
    )
    project.add_artifact(art)
    return OperationResult(status="ok", outputs=[art.id])


def _error_handler(req, project, ctx):
    raise RuntimeError("handler blew up")


def _partial_handler(req, project, ctx):
    return OperationResult(status="partial", warnings=["check this"])


# --- register_handler / get_handler ---

def test_register_and_get_handler(clean_handlers):
    register_handler(OperationKind.ISOLATION, _ok_handler)
    assert get_handler(OperationKind.ISOLATION) is _ok_handler


def test_last_registration_wins(clean_handlers):
    register_handler(OperationKind.ISOLATION, _ok_handler)
    register_handler(OperationKind.ISOLATION, _partial_handler)
    assert get_handler(OperationKind.ISOLATION) is _partial_handler


def test_get_handler_unregistered_raises(clean_handlers):
    with pytest.raises(NotImplementedError, match="isolation"):
        get_handler(OperationKind.ISOLATION)


def test_handler_decorator(clean_handlers):
    @handler(OperationKind.DRILL)
    def handle_drill(req, project, ctx):
        return OperationResult(status="ok")

    assert get_handler(OperationKind.DRILL) is handle_drill


# --- OperationRunner.validate ---

def test_validate_clean(clean_handlers, ctx, project):
    register_handler(OperationKind.IMPORT_GERBER, _ok_handler)
    op = OperationNode(kind=OperationKind.IMPORT_GERBER.value)
    project.add_operation(op)
    runner = OperationRunner(project, ctx)
    assert runner.validate() == []


def test_validate_missing_handler(clean_handlers, ctx, project):
    op = OperationNode(kind=OperationKind.ISOLATION.value, params={"tool_dia": 0.1})
    project.add_operation(op)
    errors = OperationRunner(project, ctx).validate()
    assert any("isolation" in e for e in errors)


def test_validate_missing_required_param(clean_handlers, ctx, project):
    register_handler(OperationKind.ISOLATION, _ok_handler)
    op = OperationNode(kind=OperationKind.ISOLATION.value, params={})  # missing tool_dia
    project.add_operation(op)
    errors = OperationRunner(project, ctx).validate()
    assert any("tool_dia" in e for e in errors)


def test_validate_unknown_operation_kind_returns_error(clean_handlers, ctx, project):
    op = OperationNode(kind="future_operation")
    project.add_operation(op)
    errors = OperationRunner(project, ctx).validate()
    assert any("future_operation" in error for error in errors)


def test_validate_skips_done_ops(clean_handlers, ctx, project):
    # A done op with no handler should produce no error.
    op = OperationNode(kind=OperationKind.ISOLATION.value, status="done")
    project.add_operation(op)
    assert OperationRunner(project, ctx).validate() == []


def test_validate_skips_error_ops(clean_handlers, ctx, project):
    op = OperationNode(kind=OperationKind.ISOLATION.value, status="error")
    project.add_operation(op)
    assert OperationRunner(project, ctx).validate() == []


# --- run_all ---

def test_run_all_executes_and_marks_done(clean_handlers, ctx, project):
    register_handler(OperationKind.IMPORT_GERBER, _ok_handler)
    op = OperationNode(kind=OperationKind.IMPORT_GERBER.value)
    project.add_operation(op)
    OperationRunner(project, ctx).run_all()
    assert op.status == "done"


def test_run_all_dry_run_does_not_execute(clean_handlers, ctx, project):
    called = []

    def spy(req, proj, c):
        called.append(True)
        return OperationResult(status="ok")

    register_handler(OperationKind.IMPORT_GERBER, spy)
    op = OperationNode(kind=OperationKind.IMPORT_GERBER.value)
    project.add_operation(op)
    OperationRunner(project, ctx).run_all(dry_run=True)
    assert called == []
    assert op.status == "pending"


def test_run_all_respects_cancel(clean_handlers, project):
    flag = threading.Event()
    flag.set()
    ctx = HeadlessAdapter(cancel=flag)
    register_handler(OperationKind.IMPORT_GERBER, _ok_handler)
    op = OperationNode(kind=OperationKind.IMPORT_GERBER.value)
    project.add_operation(op)
    OperationRunner(project, ctx).run_all()
    # cancel was set before the loop; op should remain pending.
    assert op.status == "pending"


def test_run_all_stops_when_ready_operation_has_invalid_params(
    clean_handlers, ctx, project
):
    register_handler(OperationKind.ISOLATION, _ok_handler)
    op = OperationNode(kind=OperationKind.ISOLATION.value, params={})
    project.add_operation(op)

    OperationRunner(project, ctx).run_all()

    assert op.status == "pending"


def test_run_all_partial_counts_as_done(clean_handlers, ctx, project):
    register_handler(OperationKind.IMPORT_GERBER, _partial_handler)
    op = OperationNode(kind=OperationKind.IMPORT_GERBER.value)
    project.add_operation(op)
    OperationRunner(project, ctx).run_all()
    assert op.status == "done"


def test_run_all_chained_operations(clean_handlers, ctx, project):
    """An operation-node dependency executes after its producer."""
    doc = Document(name="top.gbr")
    project.add_document(doc)

    calls = []

    def isolation_handler(req, proj, c):
        calls.append("isolation")
        return _ok_handler_with_artifact(req, proj, c)

    def export_handler(req, proj, c):
        calls.append(("export", list(req.inputs)))
        return _ok_handler(req, proj, c)

    register_handler(OperationKind.ISOLATION, isolation_handler)
    register_handler(OperationKind.EXPORT_GCODE, export_handler)

    iso_op = OperationNode(
        kind=OperationKind.ISOLATION.value,
        inputs=[doc.id],
        params={"tool_dia": 0.1},
    )
    project.add_operation(iso_op)

    export_op = OperationNode(
        kind=OperationKind.EXPORT_GCODE.value,
        inputs=[iso_op.id],
    )
    project.add_operation(export_op)

    OperationRunner(project, ctx).run_all()
    assert iso_op.status == "done"
    assert export_op.status == "done"
    assert calls == ["isolation", ("export", [iso_op.outputs[0]])]


# --- run_one ---

def test_run_one_executes_single_op(clean_handlers, ctx, project):
    register_handler(OperationKind.IMPORT_GERBER, _ok_handler)
    op = OperationNode(kind=OperationKind.IMPORT_GERBER.value)
    project.add_operation(op)
    result = OperationRunner(project, ctx).run_one(op.id)
    assert result.status == "ok"
    assert op.status == "done"


def test_run_one_handler_exception_marks_error(clean_handlers, ctx, project):
    register_handler(OperationKind.ISOLATION, _error_handler)
    op = OperationNode(
        kind=OperationKind.ISOLATION.value,
        params={"tool_dia": 0.1},
    )
    project.add_operation(op)
    result = OperationRunner(project, ctx).run_one(op.id)
    assert result.status == "error"
    assert op.status == "error"
    assert "handler blew up" in result.error


def test_run_one_missing_param_leaves_pending(clean_handlers, ctx, project):
    register_handler(OperationKind.ISOLATION, _ok_handler)
    op = OperationNode(kind=OperationKind.ISOLATION.value, params={})  # missing tool_dia
    project.add_operation(op)
    result = OperationRunner(project, ctx).run_one(op.id)
    assert result.status == "error"
    # Op stays pending so it can be fixed and re-queued without graph corruption.
    assert op.status == "pending"


def test_run_one_records_wall_ms(clean_handlers, ctx, project):
    register_handler(OperationKind.IMPORT_GERBER, _ok_handler)
    op = OperationNode(kind=OperationKind.IMPORT_GERBER.value)
    project.add_operation(op)
    result = OperationRunner(project, ctx).run_one(op.id)
    assert "wall_ms" in result.timings
    assert result.timings["wall_ms"] >= 0


def test_run_one_populates_op_outputs(clean_handlers, ctx, project):
    register_handler(OperationKind.ISOLATION, _ok_handler_with_artifact)
    op = OperationNode(
        kind=OperationKind.ISOLATION.value,
        params={"tool_dia": 0.1},
    )
    project.add_operation(op)
    result = OperationRunner(project, ctx).run_one(op.id)
    assert result.outputs
    assert op.outputs == result.outputs


def test_run_one_sets_artifact_producer_operation_id(clean_handlers, ctx, project):
    register_handler(OperationKind.ISOLATION, _ok_handler_with_artifact)
    op = OperationNode(
        kind=OperationKind.ISOLATION.value,
        params={"tool_dia": 0.1},
    )
    project.add_operation(op)

    result = OperationRunner(project, ctx).run_one(op.id)

    artifact = project.artifacts[result.outputs[0]]
    assert artifact.producer_op == op.id
