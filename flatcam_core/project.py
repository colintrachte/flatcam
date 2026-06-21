"""Project / document / operation graph model.

This is the runtime twin of the contracts/v1 .lwf schema.  Build them
together so they never diverge: Project serialises directly to project.lwf.

Dependency graph invariant (mirroring the existing FlatCAM workflow):
    Gerber(doc) → Isolation(op) → Toolpath(artifact) → ExportGCode(op) → GCode(artifact)

OperationRunner walks ready_operations() in topological order.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ArtifactKind(str, Enum):
    GERBER = "gerber"
    EXCELLON = "excellon"
    GEOMETRY = "geometry"
    TOOLPATH = "toolpath"
    GCODE = "gcode"


@dataclass
class Document:
    """An imported source file (Gerber, Excellon, …)."""

    name: str = ""
    kind: ArtifactKind = ArtifactKind.GERBER
    source_path: Optional[str] = None
    data: Any = None            # native camlib object (Gerber, Excellon, …)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Artifact:
    """Output produced by an operation (toolpath, G-code, …).

    source_request stores the OperationRequest.parameters snapshot that
    produced this artifact.  Compare against the current node params to answer
    "is this artifact stale?" without re-running anything.
    """

    name: str = ""
    kind: ArtifactKind = ArtifactKind.TOOLPATH
    producer_op: Optional[str] = None   # OperationNode.id that created this
    source_request: Optional[Dict[str, Any]] = None
    data: Any = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class OperationNode:
    """A node in the operation dependency graph.

    inputs:  IDs of Documents or Artifacts this operation reads.
    outputs: IDs of Artifacts this operation produced (filled after execution).
    status:  pending | running | done | error
    """

    kind: str = ""
    inputs: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    outputs: List[str] = field(default_factory=list)
    status: str = "pending"
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Project:
    """Top-level container — the runtime twin of project.lwf."""

    name: str = "Untitled"
    documents: Dict[str, Document] = field(default_factory=dict)
    operations: Dict[str, OperationNode] = field(default_factory=dict)
    artifacts: Dict[str, Artifact] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # --- mutation helpers ---

    def add_document(self, doc: Document) -> str:
        self.documents[doc.id] = doc
        return doc.id

    def add_operation(self, op: OperationNode) -> str:
        self.operations[op.id] = op
        return op.id

    def add_artifact(self, art: Artifact) -> str:
        self.artifacts[art.id] = art
        return art.id

    # --- graph traversal ---

    def _available_ids(self) -> set:
        return set(self.documents) | set(self.artifacts)

    def ready_operations(self) -> List[OperationNode]:
        """Return pending operations whose every input is already satisfied."""
        available = self._available_ids()
        return [
            op for op in self.operations.values()
            if op.status == "pending"
            and all(inp in available for inp in op.inputs)
        ]

    def stale_operations(self) -> List[OperationNode]:
        """Return done operations that have at least one missing output artifact."""
        return [
            op for op in self.operations.values()
            if op.status == "done"
            and any(oid not in self.artifacts for oid in op.outputs)
        ]
