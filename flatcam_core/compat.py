"""AppContextFacade — bridges AppContext to the duck-type interface camlib expects.

camlib classes use ``self.app`` for logging, progress, config, cancellation, and
a handful of UI hooks.  This module provides a facade that satisfies that interface
using only an AppContext, so camlib can run headless without a single line changed.

Usage::

    from flatcam_core import HeadlessAdapter
    from flatcam_core.compat import AppContextFacade
    from appParsers.ParseGerber import Gerber

    ctx = HeadlessAdapter(config={**GERBER_DEFAULTS, 'units': 'mm'})
    facade = AppContextFacade(ctx)

    gerber = Gerber.__new__(Gerber)
    gerber.app = facade          # must be set before __init__
    gerber.__init__()
    gerber.parse_file('/path/to/board.gbr')
    gerber.create_geometry()
    toolpath = gerber.isolation_geometry(offset=0.05, passes=0)
"""
from __future__ import annotations

import logging
from collections import ChainMap
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional

from .context import AppContext


# ---------------------------------------------------------------------------
# Minimum config defaults so headless callers don't need to know every key.
# Values mirror FlatCAM's own application defaults.
# ---------------------------------------------------------------------------
HEADLESS_DEFAULTS: Dict[str, Any] = {
    # units / display
    "units": "mm",
    "decimals": 4,
    "dec_format": 4,
    # Gerber parser
    "gerber_circle_steps": 64,
    "gerber_def_zeros": "L",
    "gerber_def_units": "MM",
    "gerber_simplification": False,
    "gerber_simp_tolerance": 0.001,
    "gerber_use_buffer_for_union": True,
    "gerber_buffering": "full",
    "gerber_extra_buffering": False,
    "gerber_clean_apertures": True,
    # geometry / camlib
    "global_tolerance": 0.01,
    "geometry_circle_steps": 64,
    "cncjob_steps_per_circle": 64,
    "cncjob_coords_type": "G",
    "cncjob_coords_decimals": 4,
    "cncjob_fr_decimals": 2,
    "cncjob_annotation_fontsize": 9,
    "cncjob_annotation_fontcolor": "#000000",
    "cncjob_bed_max_x": 0,
    "cncjob_bed_max_y": 0,
    "cncjob_bed_offset_x": 0,
    "cncjob_bed_offset_y": 0,
    "cncjob_bed_skew_x": 0,
    "cncjob_bed_skew_y": 0,
    "cncjob_travel_fill": "#ffffff",
    "cncjob_travel_line": "#ffffff",
    "cncjob_plot_fill": "#ffffff",
    "cncjob_plot_line": "#ffffff",
    "global_theme": "default",
    # Excellon
    "excellon_search_time": 0,
    # geometry tools defaults
    "geometry_paths_only": False,
    "geometry_feedrate": 100,
    "geometry_feedrate_z": 60,
    "geometry_feedrate_rapid": 1500,
    "geometry_dwelltime": 1000,
    "geometry_startz": None,
    "geometry_endz": 2.0,
    "geometry_endxy": "",
    "geometry_depthperpass": 0.1,
    "geometry_toolchangez": 20.0,
    "geometry_toolchangexy": "0.0,0.0",
    "geometry_f_plunge": False,
    # mill / drill
    "tools_mill_tooldia": 1.0,
    "tools_mill_cutz": -0.1,
    "tools_mill_travelz": 2.0,
    "tools_mill_feedrate": 100,
    "tools_mill_feedrate_z": 60,
    "tools_mill_feedrate_rapid": 1500,
    "tools_mill_dwelltime": 1000,
    "tools_mill_startz": None,
    "tools_mill_endz": 2.0,
    "tools_mill_endxy": "",
    "tools_mill_toolchangez": 20.0,
    "tools_mill_toolchangexy": "0.0,0.0",
    "tools_mill_extracut_length": 0.0,
    "tools_mill_optimization_type": "B",
    "tools_mill_search_time": 0,
    "tools_mill_f_plunge": False,
    "tools_mill_spindledir": "CW",
    "tools_solderpaste_pp": "default",
    "tools_drill_toolchangexy": "0.0,0.0",
}


# ---------------------------------------------------------------------------
# Internal no-op stubs for UI objects camlib touches in __init__ paths
# ---------------------------------------------------------------------------

class _NoopShapeCollection:
    """Stand-in for VisPy/Matplotlib shape collections (live-display only)."""
    def add(self, *args, **kwargs): pass
    def clear(self, *args, **kwargs): pass
    def redraw(self, *args, **kwargs): pass


class _NoopPlotCanvas:
    """Stand-in for the VisPy canvas; only new_shape_collection() is called."""
    def new_shape_collection(self, *args, **kwargs) -> _NoopShapeCollection:
        return _NoopShapeCollection()


class _NoopExcAreas:
    """No-op exclusion-area manager (headless jobs carry no exclusion zones)."""
    exclusion_areas_storage: list = []

    def travel_coordinates(self, *args, **kwargs) -> list:
        return []


class _SignalProxy:
    """Mimics a Qt signal's .emit() so camlib's ``self.app.inform.emit(msg)`` works."""

    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    def emit(self, message: str) -> None:
        self._ctx.inform(message)


class _ProcContainer:
    """Routes ``proc_container.update_view_text()`` to ctx.log.debug()."""

    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    def update_view_text(self, text: str, clear: bool = False) -> None:
        if text and text.strip():
            self._ctx.log.debug("progress: %s", text.strip())


# Singletons — these carry no per-request state so one instance is fine.
_NOOP_CANVAS = _NoopPlotCanvas()
_NOOP_EXC_AREAS = _NoopExcAreas()


# ---------------------------------------------------------------------------
# AppContextFacade — the public API
# ---------------------------------------------------------------------------

class AppContextFacade:
    """Exposes the duck-type ``self.app`` interface that camlib expects.

    Set this on camlib objects **before** calling ``__init__``::

        facade = AppContextFacade(ctx)
        obj = SomeGeometryClass.__new__(SomeGeometryClass)
        obj.app = facade
        obj.__init__(...)

    The facade merges caller-supplied config with :data:`HEADLESS_DEFAULTS`,
    so callers only need to override the keys they care about.
    """

    def __init__(
        self,
        ctx: AppContext,
        extra_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._ctx = ctx
        self._signal = _SignalProxy(ctx)
        self._proc = _ProcContainer(ctx)
        # ChainMap: caller's ctx.config wins, then any extra, then built-in defaults.
        extra = extra_config or {}
        self._options: Mapping[str, Any] = MappingProxyType(
            {**HEADLESS_DEFAULTS, **extra, **dict(ctx.config)}
        )

    # --- logging ---

    @property
    def log(self) -> logging.Logger:
        return self._ctx.log

    # --- messaging (camlib uses signal .emit() pattern) ---

    @property
    def inform(self) -> _SignalProxy:
        return self._signal

    @property
    def inform_no_echo(self) -> _SignalProxy:
        return self._signal

    # --- config / options ---

    @property
    def options(self) -> Mapping[str, Any]:
        return self._options

    @property
    def app_units(self) -> str:
        return str(self._options.get("units", "mm"))

    @property
    def decimals(self) -> int:
        return int(self._options.get("decimals", 4))

    @property
    def dec_format(self) -> int:
        return int(self._options.get("dec_format", 4))

    # --- progress ---

    @property
    def proc_container(self) -> _ProcContainer:
        return self._proc

    # --- cancellation ---

    @property
    def abort_flag(self) -> bool:
        return self._ctx.cancel.is_set()

    # --- preprocessors ---

    @property
    def preprocessors(self) -> Dict[str, Any]:
        return self._ctx.get_preprocessors()

    # --- exclusion areas (no-op headless) ---

    @property
    def exc_areas(self) -> _NoopExcAreas:
        return _NOOP_EXC_AREAS

    # --- display / canvas (no-op headless) ---

    @property
    def use_3d_engine(self) -> bool:
        # Always True so Geometry.__init__ takes the VisPy branch and
        # calls plotcanvas.new_shape_collection() — our no-op — instead of
        # importing appGUI.PlotCanvasLegacy which drags in Qt widgets.
        return True

    @property
    def plotcanvas(self) -> _NoopPlotCanvas:
        return _NOOP_CANVAS

    @property
    def ui(self) -> None:
        return None
