"""OperationRunner — walks the Project dependency graph and executes operations.

Handler registration:

    from flatcam_core.runner import register_handler
    from flatcam_core.operations import OperationKind

    def handle_isolation(req, project, ctx):
        ...
        return OperationResult(status="ok", outputs=[art_id])

    register_handler(OperationKind.ISOLATION, handle_isolation)

Handlers live in flatcam_core/handlers/ (one file per operation) and are
wired up by each adapter (HeadlessAdapter wires them at service start;
DesktopAdapter wires them in appMain).
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict

from .context import AppContext, Event
from .operations import REQUIRED_PARAMS, OperationKind, OperationRequest, OperationResult
from .project import OperationNode, Project

# Module-level handler registry: OperationKind.value → callable
_HANDLERS: Dict[str, Callable] = {}


def register_handler(kind: OperationKind, fn: Callable) -> None:
    """Register fn as the handler for kind.  Last registration wins."""
    _HANDLERS[kind.value] = fn


def handler(kind: OperationKind) -> Callable:
    """Decorator form of register_handler.

        @handler(OperationKind.ISOLATION)
        def handle_isolation(req, project, ctx):
            ...
    """
    def decorator(fn: Callable) -> Callable:
        register_handler(kind, fn)
        return fn
    return decorator


def get_handler(kind: OperationKind) -> Callable:
    key = kind.value if isinstance(kind, OperationKind) else str(kind)
    if key not in _HANDLERS:
        raise NotImplementedError(
            f"No handler registered for operation '{key}'. "
            f"Registered: {sorted(_HANDLERS)}"
        )
    return _HANDLERS[key]


class OperationRunner:
    """Execute pending operations on a Project in topological order.

    Each OperationRunner is bound to one Project and one AppContext so the
    per-job cancel flag and per-request config snapshot are isolated.
    """

    def __init__(self, project: Project, ctx: AppContext) -> None:
        self.project = project
        self.ctx = ctx

    def validate(self) -> list:
        """Return validation errors for all pending operations without executing.

        Checks: handler registered, required params present.
        Returns a list of error strings (empty = clean).
        """
        errors: list = []
        for op in self.project.operations.values():
            if op.status != "pending":
                continue
            errors.extend(self._validate_params(op))
            try:
                get_handler(OperationKind(op.kind))
            except NotImplementedError as exc:
                errors.append(str(exc))
        return errors

    def run_all(self, *, dry_run: bool = False) -> None:
        """Execute all pending operations until the graph is stable.

        dry_run=True validates params and handler registration for every pending
        operation but does not call any handler or modify the project graph.
        Useful for CI preflight and UI pre-run checks.
        """
        if dry_run:
            for err in self.validate():
                self.ctx.log.error("dry-run: %s", err)
            return

        while True:
            ready = self.project.ready_operations()
            if not ready:
                break
            for op in ready:
                if self.ctx.cancel.is_set():
                    return
                self._execute(op)

    def run_one(self, op_id: str) -> OperationResult:
        op = self.project.operations[op_id]
        return self._execute(op)

    def _validate_params(self, op: OperationNode) -> list:
        required = REQUIRED_PARAMS.get(op.kind, [])
        missing = [k for k in required if k not in op.params]
        if missing:
            return [f"Operation '{op.kind}' missing required params: {missing}"]
        return []

    def _execute(self, op: OperationNode) -> OperationResult:
        # Validate before touching op.status so a bad config stays "pending".
        param_errors = self._validate_params(op)
        if param_errors:
            for err in param_errors:
                self.ctx.log.error(err)
            return OperationResult(status="error", error="; ".join(param_errors))

        op.status = "running"
        self.ctx.emit(Event(
            type="progress",
            source=op.kind,
            level="info",
            message=f"Starting {op.kind}",
            percent=0,
        ))

        t0 = time.perf_counter()
        result: OperationResult

        try:
            _handler = get_handler(OperationKind(op.kind))
            req = OperationRequest(
                kind=OperationKind(op.kind),
                inputs=list(op.inputs),
                parameters=dict(op.params),
            )
            result = _handler(req, self.project, self.ctx)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            result.timings["wall_ms"] = elapsed_ms
            op.outputs = list(result.outputs)
            # "partial" means outputs exist despite warnings — treat as done.
            op.status = "done" if result.status in ("ok", "partial") else "error"

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.ctx.log.exception("Operation %s failed", op.kind)
            result = OperationResult(
                status="error",
                error=str(exc),
                timings={"wall_ms": elapsed_ms},
            )
            op.status = "error"

        final_level = "info" if result.status in ("ok", "partial") else "error"
        self.ctx.emit(Event(
            type="done",
            source=op.kind,
            level=final_level,
            message=(
                f"{op.kind} finished in {result.timings.get('wall_ms', 0):.0f} ms"
                + (f" [{len(result.warnings)} warning(s)]" if result.warnings else "")
                if result.status in ("ok", "partial")
                else f"{op.kind} failed: {result.error}"
            ),
            percent=100,
        ))
        return result
