"""MachineBackend — formal abstraction for G-code / machine-protocol generation.

This is the flatcam_core formalization of the existing appPreProcessor.PreProc
interface.  Key improvements over the existing system:

* **Typed params** — ``ToolpathParams`` replaces the untyped ``AttrDict(CNCjob.__dict__)``
  bag passed as ``p`` to every preprocessor method.
* **Shared default implementations** — ``position_code``, ``startz_code``, and
  ``dwell_code`` are implemented once on ``MachineBackend`` instead of being
  copy-pasted across 27 preprocessors.
* **``MachineRegistry``** — explicit, typed registry with a clear ``__getitem__``
  so callers no longer use raw string-keyed dicts.
* **``PreProcAdapter``** — wraps existing ``appPreProcessor.PreProc`` instances
  under the new interface; the legacy path keeps working without any changes to
  the 28 existing preprocessor files.

Relationship to existing code
------------------------------
* ``appPreProcessor.PreProc`` is the *existing* abstract base (11 @abstractmethods).
* ``MachineBackend`` is the *new* formalization — same contract, typed params, shared
  defaults.  New backends subclass ``MachineBackend``; legacy backends are wrapped
  in ``PreProcAdapter``.
* ``load_machine_registry()`` loads the bundled preprocessor files and returns a
  ``MachineRegistry`` ready for headless use.
"""
from __future__ import annotations

import glob
import importlib.util
import os
import types
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# ToolpathParams — typed replacement for AttrDict(CNCjob.__dict__)
# ---------------------------------------------------------------------------

@dataclass
class ToolpathParams:
    """Typed parameter bundle passed to every MachineBackend method.

    This replaces the untyped ``AttrDict(CNCjob.__dict__)`` (the ``p`` argument
    in all existing preprocessor methods).  All fields map 1-to-1 to attributes
    on ``CNCjob`` or to ``CNCjob.options`` entries.

    ``extra`` is an escape hatch for dialect-specific fields (laser power, Roland
    feedrate units, etc.) that are not part of the common vocabulary.
    """

    # --- coordinates (set per-move via doformat kwargs) ---
    x: float = 0.0
    y: float = 0.0

    # --- Z heights ---
    z_cut: float = -0.1          # cut depth (negative = into material)
    z_move: float = 2.0          # safe travel Z
    z_end: float = 2.0           # park Z at end of job
    startz: Optional[float] = None   # optional explicit start Z
    z_toolchange: float = 20.0   # Z height for toolchange

    # --- feedrates ---
    feedrate: float = 100.0
    z_feedrate: float = 60.0
    feedrate_rapid: float = 1500.0

    # --- spindle ---
    spindlespeed: Optional[float] = None
    spindledir: str = "CW"       # "CW" | "CCW"
    dwell: bool = True
    dwelltime: float = 1000.0    # milliseconds

    # --- tool ---
    tool: int = 1
    tooldia: float = 1.0         # alias for type clarity
    toolC: float = 1.0           # CNCjob internal name (also tool diameter)
    toolchange: bool = False
    xy_toolchange: Optional[List[float]] = None   # [x, y] or None
    xy_end: Optional[List[float]] = None          # [x, y] or None
    f_plunge: bool = False       # use feedrate for plunge instead of rapid

    # --- depth strategy ---
    multidepth: bool = False
    z_depthpercut: float = 0.1

    # --- units / formatting ---
    units: str = "MM"            # "MM" | "IN"
    coords_decimals: int = 4
    fr_decimals: int = 2
    decimals: int = 4            # general display precision

    # --- bed correction (shear + offset) ---
    # Variable names match the AttrDict keys used in preprocessors.
    _bed_offset_x: float = 0.0
    _bed_offset_y: float = 0.0
    _bed_skew_x: float = 0.0    # X shear due to bed tilt (mm)
    _bed_skew_y: float = 0.0    # Y shear
    _bed_limit_x: float = 1.0   # bed X extent used as shear divisor
    _bed_limit_y: float = 1.0   # bed Y extent used as shear divisor

    # --- misc CNCjob state ---
    steps_per_circle: int = 64
    pp_geometry_name: str = "default"
    pp_excellon_name: str = "default"
    use_ui: bool = False

    # --- per-object metadata (replaces p['obj_options']) ---
    obj_options: Dict[str, Any] = field(default_factory=lambda: {
        "type": "Geometry",
        "xmin": 0.0, "xmax": 0.0,
        "ymin": 0.0, "ymax": 0.0,
        "tool_dia": 1.0,
    })

    # --- per-tool list (replaces p['tools']) ---
    tools: Dict[Any, Any] = field(default_factory=dict)

    # --- escape hatch for dialect-specific keys ---
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_attrdict(self) -> Any:
        """Convert to the AttrDict expected by legacy PreProc methods.

        Imports camlib.AttrDict lazily to avoid a hard dependency at module load.
        """
        from camlib import AttrDict  # type: ignore[import]
        d = AttrDict()
        for f_name, f_val in self.__dict__.items():
            d[f_name] = f_val
        d.update(self.extra)
        return d


# ---------------------------------------------------------------------------
# MachineBackend ABC
# ---------------------------------------------------------------------------

class MachineBackend(ABC):
    """Abstract machine backend — formal interface for G-code / protocol generation.

    Subclass this to create new backends.  Existing preprocessors are usable via
    ``PreProcAdapter`` without any changes to their source files.

    All methods receive a ``ToolpathParams`` and return a plain ``str``.  The
    caller (``OperationRunner`` or ``CNCjob.doformat``) appends newlines and
    handles sequencing.
    """

    include_header: bool = True  # read by export layer to decide whether to write header

    # --- abstract methods (must implement) ---

    @abstractmethod
    def start_code(self, p: ToolpathParams) -> str:
        """Full job header block (unit selection, modal codes, bounding-box comment)."""

    @abstractmethod
    def lift_code(self, p: ToolpathParams) -> str:
        """Rapid vertical retract to safe travel height."""

    @abstractmethod
    def down_code(self, p: ToolpathParams) -> str:
        """Controlled vertical plunge to cut depth."""

    @abstractmethod
    def toolchange_code(self, p: ToolpathParams) -> str:
        """Full toolchange sequence (M5, Z-retract, T-select, M6, M0, …)."""

    @abstractmethod
    def up_to_zero_code(self, p: ToolpathParams) -> str:
        """Intermediate retract to material surface (Z=0) before full lift."""

    @abstractmethod
    def rapid_code(self, p: ToolpathParams) -> str:
        """Fast horizontal travel move (G00 / PU / …)."""

    @abstractmethod
    def linear_code(self, p: ToolpathParams) -> str:
        """Cutting horizontal move at set feedrate (G01 / PD / …)."""

    @abstractmethod
    def end_code(self, p: ToolpathParams) -> str:
        """Final park moves at end of job."""

    @abstractmethod
    def feedrate_code(self, p: ToolpathParams) -> str:
        """Set XY cutting feedrate."""

    @abstractmethod
    def spindle_code(self, p: ToolpathParams) -> str:
        """Spindle-on / laser-on command."""

    @abstractmethod
    def spindle_stop_code(self, p: ToolpathParams) -> str:
        """Spindle-off / laser-off command."""

    # --- concrete defaults (override when needed) ---

    def startz_code(self, p: ToolpathParams) -> str:
        """One-time initial Z move at job start.  Empty string if startz is None."""
        if p.startz is None:
            return ""
        return "G00 Z%.*f" % (p.coords_decimals, p.startz)

    def dwell_code(self, p: ToolpathParams) -> str:
        """Pause after spindle-on to let spindle reach target speed."""
        if p.dwell and p.dwelltime:
            return "G4 P%s" % p.dwelltime
        return ""

    def position_code(self, p: ToolpathParams) -> str:
        """Standard XY position string with bed-skew and offset correction.

        Eliminates the copy-paste of this logic across all 27 existing preprocessors.
        Formula (from default.py):
            x_fin = (x + x_offset) + (y / bed_limit_y) * skew_x   if skew_x != 0
            y_fin = (y + y_offset) + (x / bed_limit_x) * skew_y   if skew_y != 0
        Override for non-standard coordinate systems (HPGL, RML-1, …).
        """
        if p._bed_skew_x == 0:
            x_pos = p.x + p._bed_offset_x
        else:
            x_pos = (p.x + p._bed_offset_x) + (p.y / p._bed_limit_y) * p._bed_skew_x

        if p._bed_skew_y == 0:
            y_pos = p.y + p._bed_offset_y
        else:
            y_pos = (p.y + p._bed_offset_y) + (p.x / p._bed_limit_x) * p._bed_skew_y

        fmt = "%.*f"
        return ("X" + fmt + " Y" + fmt) % (p.coords_decimals, x_pos, p.coords_decimals, y_pos)


# ---------------------------------------------------------------------------
# MachineRegistry
# ---------------------------------------------------------------------------

class MachineRegistry:
    """Registry of available machine backends.

    Dict-like so that legacy ``self.app.preprocessors[name]`` call-sites keep
    working when the registry is injected as the preprocessors value.
    """

    def __init__(self) -> None:
        self._backends: Dict[str, MachineBackend] = {}

    def register(self, name: str, backend: MachineBackend) -> None:
        self._backends[name] = backend

    def get(self, name: str) -> MachineBackend:
        if name not in self._backends:
            raise KeyError(
                f"No machine backend registered for '{name}'. "
                f"Available: {self.names()}"
            )
        return self._backends[name]

    def names(self) -> List[str]:
        return sorted(self._backends)

    def __contains__(self, name: str) -> bool:
        return name in self._backends

    def __getitem__(self, name: str) -> MachineBackend:
        return self.get(name)

    def __len__(self) -> int:
        return len(self._backends)

    def items(self):
        return self._backends.items()

    def keys(self):
        return self._backends.keys()

    def values(self):
        return self._backends.values()


# ---------------------------------------------------------------------------
# PreProcAdapter — legacy bridge
# ---------------------------------------------------------------------------

class PreProcAdapter(MachineBackend):
    """Wraps an existing appPreProcessor.PreProc instance as a MachineBackend.

    Allows the 28 bundled preprocessors to be used under the new typed interface
    without any changes to their source files.  When new MachineBackend subclasses
    exist for a dialect, retire the adapter for that preprocessor.
    """

    def __init__(self, preproc: Any) -> None:
        self._pp = preproc
        self.include_header = getattr(preproc, "include_header", True)

    # --- internal helpers ---

    def _call(self, method_name: str, p: ToolpathParams, **kwargs: Any) -> str:
        """Convert ToolpathParams → AttrDict and delegate to the legacy preprocessor."""
        d = p.to_attrdict()
        d.update(kwargs)
        method = getattr(self._pp, method_name, None)
        if method is None:
            return ""
        try:
            result = method(d)
            return result if result is not None else ""
        except Exception:
            return ""

    # --- MachineBackend abstract methods ---

    def start_code(self, p: ToolpathParams) -> str:
        return self._call("start_code", p)

    def lift_code(self, p: ToolpathParams) -> str:
        return self._call("lift_code", p)

    def down_code(self, p: ToolpathParams) -> str:
        return self._call("down_code", p)

    def toolchange_code(self, p: ToolpathParams) -> str:
        return self._call("toolchange_code", p)

    def up_to_zero_code(self, p: ToolpathParams) -> str:
        return self._call("up_to_zero_code", p)

    def rapid_code(self, p: ToolpathParams) -> str:
        return self._call("rapid_code", p)

    def linear_code(self, p: ToolpathParams) -> str:
        return self._call("linear_code", p)

    def end_code(self, p: ToolpathParams) -> str:
        return self._call("end_code", p)

    def feedrate_code(self, p: ToolpathParams) -> str:
        return self._call("feedrate_code", p)

    def spindle_code(self, p: ToolpathParams) -> str:
        return self._call("spindle_code", p)

    def spindle_stop_code(self, p: ToolpathParams) -> str:
        return self._call("spindle_stop_code", p)

    def startz_code(self, p: ToolpathParams) -> str:
        return self._call("startz_code", p)

    def dwell_code(self, p: ToolpathParams) -> str:
        return self._call("dwell_code", p)

    def position_code(self, p: ToolpathParams) -> str:
        return self._call("position_code", p)


# ---------------------------------------------------------------------------
# load_preprocessors / load_machine_registry — headless entry points
# ---------------------------------------------------------------------------

def _default_preprocessors_dir() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "preprocessors",
    )


def load_preprocessors(
    preprocessors_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Load all bundled preprocessors and return the raw PreProc instance dict.

    The returned dict maps preprocessor names to legacy ``PreProc`` instances
    exactly as ``appPreProcessor.preprocessors`` is populated at runtime.  Pass
    this to ``HeadlessAdapter(preprocessors=...)`` so that ``CNCjob.__init__``
    and ``generate_from_geometry_2`` can reach it via ``self.app.preprocessors``.

    Importing appPreProcessor here (not at module top) keeps flatcam_core
    importable without appPreProcessor on sys.path.
    """
    from appPreProcessor import preprocessors as _pp_dict  # type: ignore[import]

    pp_dir = preprocessors_dir or _default_preprocessors_dir()
    for fpath in sorted(glob.glob(os.path.join(pp_dir, "*.py"))):
        spec = importlib.util.spec_from_file_location("FlatCAMPostProcessor", fpath)
        mod = types.ModuleType("FlatCAMPostProcessor")
        spec.loader.exec_module(mod)

    return _pp_dict  # type: ignore[return-value]


def load_machine_registry(
    preprocessors_dir: Optional[str] = None,
) -> MachineRegistry:
    """Load all bundled preprocessors and return them as a ``MachineRegistry``.

    Each preprocessor is wrapped in a ``PreProcAdapter`` so callers get the typed
    ``MachineBackend`` interface.  The returned registry also satisfies the legacy
    ``self.app.preprocessors[name]`` dict-access pattern (via ``__getitem__``).

    For headless ``CNCjob`` use, prefer :func:`load_preprocessors` which returns the
    raw PreProc dict that ``CNCjob`` and ``generate_from_geometry_2`` expect.
    """
    _pp_dict = load_preprocessors(preprocessors_dir)
    registry = MachineRegistry()
    for name, pp in _pp_dict.items():
        registry.register(name, PreProcAdapter(pp))
    return registry
