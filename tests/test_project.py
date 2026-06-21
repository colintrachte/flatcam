import uuid

import pytest

from flatcam_core import (
    Artifact,
    ArtifactKind,
    Document,
    OperationNode,
    Project,
)


# --- identity / UUID generation ---

def test_document_gets_uuid():
    doc = Document(name="top.gbr")
    uuid.UUID(doc.id)  # raises ValueError if not a valid UUID


def test_artifact_gets_uuid():
    art = Artifact(name="toolpath")
    uuid.UUID(art.id)


def test_operation_node_gets_uuid():
    op = OperationNode(kind="isolation")
    uuid.UUID(op.id)


def test_project_gets_uuid():
    proj = Project()
    uuid.UUID(proj.id)


def test_two_documents_have_different_ids():
    assert Document().id != Document().id


def test_two_projects_have_different_ids():
    assert Project().id != Project().id


# --- Project mutation helpers ---

def test_add_document_stores_and_returns_id():
    proj = Project()
    doc = Document(name="top.gbr", kind=ArtifactKind.GERBER)
    returned_id = proj.add_document(doc)
    assert returned_id == doc.id
    assert proj.documents[doc.id] is doc


def test_add_operation_stores_and_returns_id():
    proj = Project()
    op = OperationNode(kind="isolation")
    returned_id = proj.add_operation(op)
    assert returned_id == op.id
    assert proj.operations[op.id] is op


def test_add_artifact_stores_and_returns_id():
    proj = Project()
    art = Artifact(name="toolpath", kind=ArtifactKind.TOOLPATH)
    returned_id = proj.add_artifact(art)
    assert returned_id == art.id
    assert proj.artifacts[art.id] is art


# --- ready_operations ---

def test_ready_operations_no_inputs(project):
    op = OperationNode(kind="import_gerber", inputs=[])
    project.add_operation(op)
    ready = project.ready_operations()
    assert op in ready


def test_ready_operations_satisfied_inputs(project):
    doc = Document(name="top.gbr")
    project.add_document(doc)
    op = OperationNode(kind="isolation", inputs=[doc.id])
    project.add_operation(op)
    assert op in project.ready_operations()


def test_ready_operations_unsatisfied_inputs(project):
    op = OperationNode(kind="isolation", inputs=["nonexistent-id"])
    project.add_operation(op)
    assert op not in project.ready_operations()


def test_ready_operations_skips_done(project):
    doc = Document()
    project.add_document(doc)
    op = OperationNode(kind="isolation", inputs=[doc.id], status="done")
    project.add_operation(op)
    assert op not in project.ready_operations()


def test_ready_operations_skips_running(project):
    op = OperationNode(kind="import_gerber", status="running")
    project.add_operation(op)
    assert op not in project.ready_operations()


def test_ready_operations_skips_error(project):
    op = OperationNode(kind="import_gerber", status="error")
    project.add_operation(op)
    assert op not in project.ready_operations()


def test_artifact_satisfies_dependent_op(project):
    art = Artifact(name="toolpath")
    project.add_artifact(art)
    op = OperationNode(kind="export_gcode", inputs=[art.id])
    project.add_operation(op)
    assert op in project.ready_operations()


# --- stale_operations ---

def test_stale_operations_missing_artifact(project):
    op = OperationNode(kind="isolation", status="done", outputs=["missing-art-id"])
    project.add_operation(op)
    assert op in project.stale_operations()


def test_stale_operations_all_outputs_present(project):
    art = Artifact(name="toolpath")
    project.add_artifact(art)
    op = OperationNode(kind="isolation", status="done", outputs=[art.id])
    project.add_operation(op)
    assert op not in project.stale_operations()


def test_stale_operations_pending_op_not_stale(project):
    op = OperationNode(kind="isolation", status="pending", outputs=["missing"])
    project.add_operation(op)
    assert op not in project.stale_operations()


def test_stale_operations_done_no_outputs_not_stale(project):
    op = OperationNode(kind="export_gcode", status="done", outputs=[])
    project.add_operation(op)
    assert op not in project.stale_operations()
