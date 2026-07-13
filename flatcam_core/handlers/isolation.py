"""Handler: generate isolation rings from a GEOMETRY artifact."""
from __future__ import annotations

from flatcam_core.compat import AppContextFacade
from flatcam_core.context import AppContext
from flatcam_core.operations import OperationKind, OperationRequest, OperationResult
from flatcam_core.project import Artifact, ArtifactKind, Project
from flatcam_core.runner import handler


@handler(OperationKind.ISOLATION)
def handle_isolation(
    req: OperationRequest, project: Project, ctx: AppContext
) -> OperationResult:
    """Run isolation_geometry on a GEOMETRY artifact (typically from import_gerber).

    Required params:
        tool_dia (float)    — cutter diameter in project units
    Optional params:
        passes   (int)      — number of isolation passes, default 1
        iso_type (int)      — 0=exteriors, 1=interiors, 2=both, default 2
        corner   (int|None) — 0=round, 1=square, 2=bevel, default None (round)

    Input:  req.inputs[0] = GEOMETRY artifact ID (from import_gerber)
    Output: TOOLPATH artifact with data = {solid_geometry: list, tool_dia: float}
    """
    from appParsers.ParseGerber import Gerber  # deferred: carries a PyQt6 import

    if not req.inputs:
        return OperationResult(status="error", error="isolation requires one input (geometry artifact id)")

    art_id = req.inputs[0]
    src_art = project.artifacts.get(art_id)
    if src_art is None:
        return OperationResult(status="error", error=f"Artifact '{art_id}' not found in project")

    art_data = src_art.data if isinstance(src_art.data, dict) else {"solid_geometry": src_art.data}
    solid_geo = art_data.get("solid_geometry")
    if solid_geo is None or (hasattr(solid_geo, "is_empty") and solid_geo.is_empty):
        return OperationResult(status="error", error="Source geometry artifact is empty")

    tool_dia = float(req.parameters["tool_dia"])
    passes = int(req.parameters.get("passes", 1))
    iso_type = int(req.parameters.get("iso_type", 2))
    corner = req.parameters.get("corner", None)

    facade = AppContextFacade(ctx)

    gerber = Gerber.__new__(Gerber)
    gerber.app = facade
    gerber.__init__()
    gerber.solid_geometry = solid_geo

    all_rings = []
    warnings = []
    for i in range(passes):
        offset = (i + 1) * tool_dia / 2.0
        result = gerber.isolation_geometry(
            offset=offset,
            iso_type=iso_type,
            corner=corner,
            passes=i,
        )
        if result is None or result == "fail":
            warnings.append(f"Pass {i + 1} produced no geometry (offset={offset:.4f})")
        else:
            items = result if isinstance(result, list) else [result]
            all_rings.extend(items)

    if not all_rings:
        return OperationResult(
            status="error",
            error=f"Isolation produced no geometry for tool_dia={tool_dia}",
        )

    out_art = Artifact(
        name=f"isolation_d{tool_dia}_p{passes}",
        kind=ArtifactKind.TOOLPATH,
        producer_op=req.operation_id,
        source_request=dict(req.parameters),
        data={"solid_geometry": all_rings, "tool_dia": tool_dia},
    )
    out_id = project.add_artifact(out_art)
    ctx.log.info("isolation: %d ring(s) → artifact %s", len(all_rings), out_id)
    return OperationResult(
        status="ok" if not warnings else "partial",
        outputs=[out_id],
        warnings=warnings,
    )
