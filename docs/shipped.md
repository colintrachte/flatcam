# FlatCAM Evo Beta — Shipped

Completed items moved out of `docs/roadmap.md`, in the same header/body format minus the
generated `Route`/`Effort`/`Chars` lines (see `docs/roadmap.md`'s format-convention section
— those stop mattering once a task is done). New completions should land here via
`python helper_scripts/route_tasks.py --complete "<title fragment>"`, not by hand-editing
both files.

---

## Critical Crashes

- [x] **Score 5 🥇 · Class 3 — Fix crash milling drill slots (Issue #619)**
      Zero-length slots crashed the app during drill-slot milling. Fixed 2026-06-19: added
      a zero-length slot guard in `process_slot_as_drills()`.

  **Implement:** `appPlugins/ToolDrilling.py`

- [x] **Score 5 🥇 · Class 2 — Fix corner-marker crash on toggle in Gerber folder (Issue #500)**
      Toggling corner markers in a Gerber folder crashed the app. Fixed 2026-06-19:
      disconnect signals before `clear_ui` in `ToolFiducials.set_tool_ui()`.

  **Implement:** `appPlugins/ToolFiducials.py`

- [x] **Score 5 🥇 · Class 2 — Fix Gerber editor delete-aperture and polygonize crashes (Issue #529)**
      The Delete Aperture button did nothing, and Polygonize crashed the editor. Fixed
      2026-06-19: corrected the delete handler (#529a) and guarded non-Polygon solids in
      polygonize (#529b).

  **Implement:** `appEditors/appGerberEditor.py`

---

## Major PCB Workflow Bugs

- [x] **Score 3 🥈 · Class 2 — Fix KiCad v7 octagonal pad rendering (Issue #687)**
      KiCad v7 octagonal pads rendered distorted. Fixed 2026-06-19:
      `ApertureMacro.default2zero(4, mods)` → `default2zero(6, mods)`.

  **Implement:** `camlib.py`

- [x] **Score 5 🥇 · Class 2 — Stop rejecting valid RS-274-X Gerber files (Issue #688)**
      Valid Gerber files were rejected as "probably not a Gerber file". Fixed 2026-06-19:
      relaxed the rejection condition to only fail when `buff_length == 0 AND area == 0`.

  **Implement:** `appParsers/ParseGerber.py`

- [x] **Score 5 🥇 · Class 2 — Fix NCC "no NCC Geometry" errors (Issue #605 / #505)**
      Fixed 2026-06-19: guarded `isinstance(solid_geometry, list)` before calling
      `.buffer(0)` in the NCC tool.

  **Implement:** `appPlugins/ToolNCC.py`

- [x] **Score 5 🥇 · Class 3 — Fix tool moving XY before lifting to safe Z mid-job (Issue #604)**
      The tool moved in XY before lifting to safe Z during exclusion-zone traversal — a
      crash-into-copper risk. Fixed 2026-06-19: swapped the order in `camlib.py`'s
      exclusion-zone traversal to lift Z at the current position first, then rapid XY.

  **Implement:** `camlib.py`

- [x] **Score 3 🥈 · Class 2 — Fix milling target combo box defaulting to first file (Issue #526)**
      The milling target combo box defaulted to the first file instead of the selected
      object. Fixed 2026-06-19: wrapped `target_radio.set_value` in `blockSignals` in
      `ToolMilling.set_tool_ui()`.

  **Implement:** `appPlugins/ToolMilling.py`

- [x] **Score 3 🥈 · Class 2 — Fix Extract Plugin source selector jumping to wrong object (Issue #528)**
      Fixed 2026-06-19: added an `if obj and obj.kind == 'gerber':` guard in
      `ToolExtract.set_tool_ui()`.

  **Implement:** `appPlugins/ToolExtract.py`

- [x] **Score 3 🥈 · Class 2 — Fix TclCommandMillDrills tool-list string parsing (Issue #561)**
      Fixed 2026-06-19: replaced the decrement counter with a `found_dias` set; also fixed
      the docstring example.

  **Implement:** `tclCommands/TclCommandMillDrills.py`

---

## Upstream PRs Applied

- [x] **Score 3 🥈 · Class 2 — Apply two items from PR #355 (partial)**
      `int()` cast around `IndexToNode()` for NumPy 2.x compatibility (fixed 2026-06-19),
      plus `tclCommands/__init__.py` importlib modernization (already done in a prior
      session).

  **Implement:** `camlib.py` · `tclCommands/__init__.py`

---

## Quality of Life

- [x] **Score 1 🥉 · Class 1 — Add default preprocessor setting for Excellon jobs (Issue #549)**
      No default preprocessor was set for Excellon jobs in Preferences. Fixed 2026-06-19:
      call `set_value` after `addItems` in `ToolsDrillPrefGroupUI.py`.

  **Implement:** `appGUI/preferences/tools/ToolsDrillPrefGroupUI.py`

- [x] **Score 1 🥉 · Class 1 — Confirm units display case is correct (Issue #405)**
      Reported units displayed as "5.4MM" instead of "5.4 mm". Already fixed: all
      preprocessors call `.lower()` on the units string.

  **Context:** `preprocessors/default.py`

- [x] **Score 1 🥉 · Class 1 — Add conda environment.yml (Issue #684)**
      No conda `environment.yml` existed for conda users. Fixed 2026-06-19: created
      `environment.yml` with conda-forge packages including GDAL.

  **Write:** `environment.yml`

---

## Legacy fixes (pre-tracking)

Fixes recorded before this roadmap/shipped convention existed. Carried over as-is from the
old `TODO.md` "Previously Fixed" table rather than reformatted — several bundle multiple
unrelated changes under one date and don't resolve to a clean single file list.

| When | What |
|---|---|
| 2026-06-19 | #619: zero-length slot crash in `ToolDrilling.process_slot_as_drills()` |
| 2026-06-19 | #500: ToolFiducials signals-before-clear_ui crash |
| 2026-06-19 | #529: Gerber editor delete handler + polygonize non-Polygon crash |
| 2026-06-19 | #687: `ApertureMacro.default2zero(4)` → `default2zero(6)` (octagonal pads) |
| 2026-06-19 | #688: Gerber parser over-rejection of region-only files |
| 2026-06-19 | #605/#505: NCC `list.buffer(0)` AttributeError |
| 2026-06-19 | #604: XY rapid before Z-lift in exclusion zone traversal |
| 2026-06-19 | #526: ToolMilling target combo wipe-on-open |
| 2026-06-19 | #528: ToolExtract selector ignores non-Gerber active objects |
| 2026-06-19 | #561: TclCommandMillDrills docstring + counter logic |
| 2026-06-19 | #549: Excellon preprocessor preference set_value |
| 2026-06-19 | PR #355: `int()` cast around `IndexToNode()` for NumPy 2.x |
| 2026-06-19 | #684: `environment.yml` created for conda users |
| 2026-06-19 | #405: confirmed already fixed (`.lower()` on units in all preprocessors) |
| 2026-06-17 | Misspellings fixed across 14 files (`toogle`, `curent`, `overriden`, `rectange`, `lenghtx`/`lenghty`, etc.) |
| 2026-06-17 | Default G-code save extension changed from `.nc` to `.gcode` |
| 2026-06-17 | Legacy project blocking dialog removed; replaced with non-blocking status-bar warning |
| 2026-06-14 | `FCLabel` startup crash: `QtCore.Signal` → `pyqtSignal` |
| 2026-06-14 | JSON project save crash on `inf`/`nan` float values (`appHandlers/appIO.py`) |
| 2026-06-14 | Panelize while-loop underflow (columns/rows reaching 0 under constrain mode) |
| 2026-06-14 | `SourceFileLoader.load_module()` → `importlib.util` in `appPreProcessor.py` |
| 2026-06-14 | `requirements.txt` cleaned: vispy pinned `<0.17`, `ortools>=9.0`, `six` removed, GDAL noted |
| Before fork | Tool-delete crash (8.994), Shapely 2.x API, NumPy deprecations, thread-safety, GRBL_11 G21/G90/G94 |
