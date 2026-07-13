"""Thin FastAPI adapter over the runtime-agnostic FlatCAM core."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import flatcam_core.handlers  # noqa: F401 -- register built-in handlers
from flatcam_core import (
    ArtifactKind,
    Document,
    HeadlessAdapter,
    OperationKind,
    OperationNode,
    OperationRunner,
    Project,
    get_handler,
)


class DocumentInput(BaseModel):
    """A source document available to an operation graph."""

    id: str | None = None
    name: str = ""
    kind: ArtifactKind = ArtifactKind.GERBER
    source_path: str | None = None


class OperationInput(BaseModel):
    """One operation in a project graph."""

    id: str | None = None
    kind: OperationKind
    inputs: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class RunInput(BaseModel):
    """A complete, stateless FlatCAM job."""

    name: str = "Untitled"
    documents: list[DocumentInput] = Field(default_factory=list)
    operations: list[OperationInput] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    include_artifact_data: bool = False


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    geo = getattr(value, "__geo_interface__", None)
    if geo is not None:
        return _json_safe(geo)
    return str(value)


def _resolve_source_path(source_path: str, source_root: Path) -> str:
    candidate = Path(source_path)
    if not candidate.is_absolute():
        candidate = source_root / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(source_root):
        raise HTTPException(422, f"Document source_path is outside the service root: {source_path}")
    return str(candidate)


def _build_project(payload: RunInput, source_root: Path) -> Project:
    project = Project(name=payload.name)
    for item in payload.documents:
        kwargs = item.model_dump(exclude={"id"})
        if item.source_path is not None:
            kwargs["source_path"] = _resolve_source_path(item.source_path, source_root)
        if item.id is not None:
            kwargs["id"] = item.id
        document = Document(**kwargs)
        if document.id in project.documents:
            raise HTTPException(422, f"Duplicate document id: {document.id}")
        project.add_document(document)

    for item in payload.operations:
        kwargs = item.model_dump(exclude={"id"})
        kwargs["kind"] = item.kind.value
        if item.id is not None:
            kwargs["id"] = item.id
        operation = OperationNode(**kwargs)
        if operation.id in project.operations or operation.id in project.documents:
            raise HTTPException(422, f"Duplicate operation id: {operation.id}")
        project.add_operation(operation)
    return project


def _validate_graph(project: Project) -> list[str]:
    errors: list[str] = []
    known_ids = set(project.documents) | set(project.operations)
    dependencies: dict[str, set[str]] = {}
    for op_id, operation in project.operations.items():
        unknown = [item for item in operation.inputs if item not in known_ids]
        if unknown:
            errors.append(f"Operation '{op_id}' has unknown inputs: {unknown}")
        dependencies[op_id] = {
            item for item in operation.inputs if item in project.operations
        }

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(op_id: str) -> None:
        if op_id in visiting:
            errors.append(f"Operation graph contains a cycle involving '{op_id}'")
            return
        if op_id in visited:
            return
        visiting.add(op_id)
        for dependency in dependencies[op_id]:
            visit(dependency)
        visiting.remove(op_id)
        visited.add(op_id)

    for op_id in dependencies:
        visit(op_id)
    return errors


def _project_response(
    project: Project,
    validation_errors: list[str],
    results: dict[str, Any] | None = None,
    *,
    include_artifact_data: bool = False,
) -> dict[str, Any]:
    project_data = asdict(project)
    if not include_artifact_data:
        for artifact in project_data["artifacts"].values():
            artifact["data"] = None
    return {
        "project": _json_safe(project_data),
        "validation_errors": validation_errors,
        "results": _json_safe(results or {}),
    }


def create_app(source_root: str | Path | None = None) -> FastAPI:
    configured_root = source_root or os.environ.get("FLATCAM_SERVICE_ROOT") or Path.cwd()
    allowed_source_root = Path(configured_root).resolve()
    service = FastAPI(
        title="FlatCAM Core API",
        version="1.0.0",
        description="Stateless HTTP execution of flatcam_core operation graphs.",
    )

    @service.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @service.get("/v1/operations")
    def operations() -> dict[str, list[str]]:
        available = []
        for kind in OperationKind:
            try:
                get_handler(kind)
            except NotImplementedError:
                continue
            available.append(kind.value)
        return {"operations": available}

    @service.post("/v1/run")
    def run(payload: RunInput) -> dict[str, Any]:
        project = _build_project(payload, allowed_source_root)
        context = HeadlessAdapter(
            config=dict(payload.config),
            logger_name=f"flatcam_service.{project.id}",
        )
        runner = OperationRunner(project, context)
        errors = _validate_graph(project) + runner.validate()
        if errors or payload.dry_run:
            return _project_response(
                project,
                errors,
                include_artifact_data=payload.include_artifact_data,
            )
        results = runner.run_all()
        return _project_response(
            project,
            [],
            results,
            include_artifact_data=payload.include_artifact_data,
        )

    return service


app = create_app()
