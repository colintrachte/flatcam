"""Handler: generate G-code from a TOOLPATH artifact (e.g. isolation rings)."""
from __future__ import annotations

from flatcam_core.compat import AppContextFacade, HEADLESS_DEFAULTS
from flatcam_core.context import AppContext, HeadlessAdapter
from flatcam_core.machine import load_preprocessors
from flatcam_core.operations import OperationKind, OperationRequest, OperationResult
from flatcam_core.project import Artifact, ArtifactKind, Project
from flatcam_core.runner import handler


class _GeoWrapper:
    """Minimal camlib geo_obj shim.

    generate_from_geometry_2 reads only ``solid_geometry`` from geo_obj.
    ``obj_options`` is touched only in error paths (z_cut==0, z_move==0);
    we carry it to avoid AttributeError if those paths are hit.
    """

    def __init__(self, solid_geometry: object, name: str = "headless") -> None:
        self.solid_geometry = solid_geometry
        self.obj_options: dict = {"name": name, "type": "Geometry"}


@handler(OperationKind.EXPORT_GCODE)
def handle_export_gcode(
    req: OperationRequest, project: Project, ctx: AppContext
) -> OperationResult:
    """Generate G-code from a TOOLPATH artifact.

    Optional params (all have safe defaults):
        tooldia          (float) — tool diameter; falls back to artifact's tool_dia
        z_cut            (float) — cut depth (negative), default -0.1
        z_move           (float) — travel height, default 2.0
        feedrate         (float) — XY feedrate mm/min, default 100
        feedrate_z       (float) — Z feedrate mm/min, default 60
        feedrate_rapid   (float) — rapid feedrate mm/min, default 1500
        preprocessor     (str)   — preprocessor name, default 'default'
        spindlespeed     (float) — spindle RPM, default None (spindle disabled)
        dwell            (bool)  — dwell after spindle-on, default False
        dwelltime        (float) — dwell duration ms, default 1000
        endz             (float) — park Z at job end, default 2.0

    Input:  req.inputs[0] = TOOLPATH artifact ID (from isolation handler)
    Output: GCODE artifact with data = {gcode: str, preprocessor: str}
    """
    from camlib import CNCjob  # deferred: heavy import, avoid at module load

    if not req.inputs:
        return OperationResult(status="error", error="export_gcode requires one input (toolpath artifact id)")

    art_id = req.inputs[0]
    art = project.artifacts.get(art_id)
    if art is None:
        return OperationResult(status="error", error=f"Artifact '{art_id}' not found in project")

    art_data = art.data if isinstance(art.data, dict) else {"solid_geometry": art.data}
    solid_geo = art_data.get("solid_geometry")
    if not solid_geo:
        return OperationResult(status="error", error="Toolpath artifact has empty solid_geometry")

    p = req.parameters
    tool_dia = float(p.get("tooldia") or art_data.get("tool_dia") or 1.0)
    z_cut = float(p.get("z_cut", -0.1))
    z_move = float(p.get("z_move", 2.0))
    feedrate = float(p.get("feedrate", 100.0))
    feedrate_z = float(p.get("feedrate_z", 60.0))
    feedrate_rapid = float(p.get("feedrate_rapid", 1500.0))
    preprocessor = str(p.get("preprocessor", "default"))
    spindlespeed = p.get("spindlespeed", None)
    dwell = bool(p.get("dwell", False))
    dwelltime = float(p.get("dwelltime", 1000.0))
    endz = float(p.get("endz", 2.0))

    # Load the raw PreProc instances — CNCjob.__init__ and generate_from_geometry_2
    # both access self.app.preprocessors[name] and need these (not PreProcAdapter wrappers).
    pp_dict = load_preprocessors()
    if preprocessor not in pp_dict:
        available = sorted(pp_dict)
        return OperationResult(
            status="error",
            error=f"Preprocessor '{preprocessor}' not found. Available: {available}",
        )

    # Build a context that carries the preprocessors dict for CNCjob.
    config = dict(HEADLESS_DEFAULTS)
    config.update(ctx.config)
    ctx_with_pp = HeadlessAdapter(
        config=config,
        cancel=ctx.cancel,
        preprocessors=pp_dict,
    )
    facade = AppContextFacade(ctx_with_pp)

    # Instantiate CNCjob headlessly (same MRO trick as Gerber).
    units = str(ctx.config.get("units", "mm")).upper()
    cnc = CNCjob.__new__(CNCjob)
    cnc.app = facade
    cnc.__init__(
        units=units,
        tooldia=tool_dia,
        z_cut=z_cut,
        z_move=z_move,
        feedrate=feedrate,
        feedrate_z=feedrate_z,
        feedrate_rapid=feedrate_rapid,
        pp_geometry_name=preprocessor,
    )
    # coords_decimals / fr_decimals are set by CNCJobObject (the GUI mixin), not by
    # camlib.CNCjob.__init__.  Set them here so preprocessors that access p.coords_decimals
    # and p.fr_decimals via doformat2()'s AttrDict find them.
    cnc.coords_decimals = int(facade.options.get("cncjob_coords_decimals", 4))
    cnc.fr_decimals = int(facade.options.get("cncjob_fr_decimals", 2))
    # obj_options is set by AppObjectTemplate (GUI mixin).  The bounding-box fields
    # appear only in G-code header comments, so zeroes are fine for headless.
    cnc.obj_options = {
        "name": "headless_gcode",
        "type": "Geometry",
        "tool_dia": tool_dia,   # read by default preprocessor's start_code
        "xmin": 0.0, "xmax": 0.0,
        "ymin": 0.0, "ymax": 0.0,
    }

    geo = _GeoWrapper(solid_geometry=solid_geo)
    raw = cnc.generate_from_geometry_2(
        geo,
        tooldia=tool_dia,
        z_cut=z_cut,
        z_move=z_move,
        feedrate=feedrate,
        feedrate_z=feedrate_z,
        feedrate_rapid=feedrate_rapid,
        spindlespeed=spindlespeed,
        dwell=dwell,
        dwelltime=dwelltime,
        endz=endz,
        pp_geometry_name=preprocessor,
        is_first=True,
    )

    # generate_from_geometry_2 returns ('fail', start_gcode) on empty output,
    # or (gcode_body, start_gcode) on success, or bare 'fail' on early errors.
    if raw is None or raw == "fail":
        return OperationResult(status="error", error="G-code generation returned fail")

    gcode_body, start_gcode = raw
    if gcode_body == "fail":
        return OperationResult(status="error", error="G-code generation produced empty output")

    full_gcode = (start_gcode or "") + (gcode_body or "")

    out_art = Artifact(
        name=f"gcode_{preprocessor}",
        kind=ArtifactKind.GCODE,
        producer_op=req.kind.value,
        source_request=dict(p),
        data={"gcode": full_gcode, "preprocessor": preprocessor},
    )
    out_id = project.add_artifact(out_art)
    ctx.log.info(
        "export_gcode: %d chars via '%s' → artifact %s",
        len(full_gcode),
        preprocessor,
        out_id,
    )
    return OperationResult(status="ok", outputs=[out_id])
