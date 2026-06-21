"""flatcam_core — runtime-agnostic FlatCAM engine library.

Qt-desktop, headless service, CLI, and future cloud are all adapters over
this package.  Nothing here imports Qt.

Quick start (headless):

    from flatcam_core import HeadlessAdapter, Project, Document, ArtifactKind
    from flatcam_core import OperationNode, OperationRunner, OperationKind
    from flatcam_core import register_handler

    ctx = HeadlessAdapter(config={...})
    proj = Project(name="my-board")
    doc_id = proj.add_document(Document(name="top.gbr", kind=ArtifactKind.GERBER))
    op_id  = proj.add_operation(OperationNode(
        kind=OperationKind.ISOLATION, inputs=[doc_id],
        params={"tool_dia": 0.1, "passes": 2},
    ))
    OperationRunner(proj, ctx).run_all()
"""

from .context import AppContext, Event, HeadlessAdapter
from .geometry import GeometryEngine, ShapelyGeometryEngine
from .operations import REQUIRED_PARAMS, OperationKind, OperationRequest, OperationResult
from .parsers import ParserRegistry
from .project import Artifact, ArtifactKind, Document, OperationNode, Project
from .runner import OperationRunner, get_handler, handler, register_handler

__all__ = [
    # context
    "AppContext",
    "Event",
    "HeadlessAdapter",
    # geometry
    "GeometryEngine",
    "ShapelyGeometryEngine",
    # operations
    "OperationKind",
    "OperationRequest",
    "OperationResult",
    "REQUIRED_PARAMS",
    # parsers
    "ParserRegistry",
    # project model
    "Artifact",
    "ArtifactKind",
    "Document",
    "OperationNode",
    "Project",
    # runner
    "OperationRunner",
    "get_handler",
    "handler",
    "register_handler",
]
