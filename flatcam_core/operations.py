from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OperationKind(str, Enum):
    """Vocabulary of operations the engine can perform."""

    IMPORT_GERBER = "import_gerber"
    IMPORT_EXCELLON = "import_excellon"
    ISOLATION = "isolation"
    DRILL = "drill"
    CUTOUT = "cutout"
    POCKET = "pocket"
    NCC_CLEAR = "ncc_clear"
    FOLLOW = "follow"
    EXPORT_GCODE = "export_gcode"


@dataclass
class OperationRequest:
    """Declarative description of work to perform.

    inputs:          IDs of Documents or Artifacts this operation reads.
    parameters:      Operation-specific kwargs (tool_dia, overlap, …).
    tool_id:         Optional reference to a tool definition.
    machine_profile: Preprocessor/dialect selection (contracts/v1 MachineProfile id).
    material_profile: Material-specific feed/speed overrides.
    """

    kind: OperationKind
    inputs: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    tool_id: Optional[str] = None
    machine_profile: Optional[str] = None
    material_profile: Optional[str] = None


@dataclass
class OperationResult:
    """Outcome returned by an operation handler.

    status:  "ok" | "partial" | "error" | "cancelled"
             "partial" means outputs were produced but with non-fatal problems;
             OperationRunner treats it the same as "ok" (node → done).
    outputs: IDs of Artifacts produced (registered in Project by the handler).
    timings: wall_ms and any sub-stage timings; stored on OperationNode.
    metrics: performance counters for dashboards / golden-timing comparisons
             (input_polygon_count, output_segment_count, peak_rss_kb, …).
    """

    status: str
    outputs: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    events: List[Any] = field(default_factory=list)
    timings: Dict[str, float] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


# Minimum required parameter keys per operation kind.
# Checked by OperationRunner before invoking a handler.
REQUIRED_PARAMS: Dict[str, List[str]] = {
    OperationKind.IMPORT_GERBER.value:    [],
    OperationKind.IMPORT_EXCELLON.value:  [],
    OperationKind.ISOLATION.value:        ["tool_dia"],
    OperationKind.DRILL.value:            ["tool_dia"],
    OperationKind.CUTOUT.value:           ["tool_dia"],
    OperationKind.POCKET.value:           ["tool_dia"],
    OperationKind.NCC_CLEAR.value:        ["tool_dia"],
    OperationKind.FOLLOW.value:           [],
    OperationKind.EXPORT_GCODE.value:     [],
}
