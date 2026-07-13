"""Handler: import a Gerber file and store parsed geometry as an Artifact."""
from __future__ import annotations

import os

from flatcam_core.compat import AppContextFacade
from flatcam_core.context import AppContext
from flatcam_core.operations import OperationKind, OperationRequest, OperationResult
from flatcam_core.project import Artifact, ArtifactKind, Project
from flatcam_core.runner import handler


@handler(OperationKind.IMPORT_GERBER)
def handle_import_gerber(
    req: OperationRequest, project: Project, ctx: AppContext
) -> OperationResult:
    """Parse a Gerber file and store solid_geometry as a GEOMETRY artifact.

    Input:  req.inputs[0] = Document ID whose source_path points to a .gbr file.
    Output: GEOMETRY artifact with data = {solid_geometry, units, tools}.
    """
    from appParsers.ParseGerber import Gerber  # deferred: carries a PyQt6 import

    if not req.inputs:
        return OperationResult(status="error", error="import_gerber requires one input (document id)")

    doc_id = req.inputs[0]
    doc = project.documents.get(doc_id)
    if doc is None:
        return OperationResult(status="error", error=f"Document '{doc_id}' not found in project")

    file_path = doc.source_path
    if not file_path or not os.path.isfile(file_path):
        return OperationResult(
            status="error",
            error=f"Gerber file not found: {file_path!r}",
        )

    facade = AppContextFacade(ctx)

    gerber = Gerber.__new__(Gerber)
    gerber.app = facade
    gerber.__init__()
    gerber.parse_file(file_path)

    art = Artifact(
        name=os.path.basename(file_path),
        kind=ArtifactKind.GEOMETRY,
        producer_op=req.operation_id,
        data={
            "solid_geometry": gerber.solid_geometry,
            "units": gerber.units,
            "tools": gerber.tools,
        },
    )
    art_id = project.add_artifact(art)
    ctx.log.info("import_gerber: %s → artifact %s", file_path, art_id)
    return OperationResult(status="ok", outputs=[art_id])
