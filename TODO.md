# FlatCAM Evo Beta — TODO
> Fork: colintrachte/flatcam (branch `mstanciu_Beta_8.995`)
> Last reviewed: 2026-06-19

---

## Critical Crashes

- [x] **Issue #619** — App crashes when milling drill slots — *Fixed 2026-06-19: zero-length slot guard in `ToolDrilling.process_slot_as_drills()`*

- [x] **Issue #500** — Corner markers crash on toggle in Gerber folder — *Fixed 2026-06-19: disconnect signals before `clear_ui` in `ToolFiducials.set_tool_ui()`*

- [x] **Issue #529** — Gerber editor: Delete aperture button does nothing; Polygonize crashes the editor — *Fixed 2026-06-19: correct delete handler (#529a); guard non-Polygon solid in polygonize (#529b)*

---

## Major PCB Workflow Bugs

- [ ] **Issue #539** — Isolation tool path offset inconsistency
  - `ToolIsolation` uses `2.0000001` divisor in iso_offset formula while the rest-machining path uses `2.0`. Change all four occurrences to `2.0`. Deliberately deferred — subtle, affects cut quality, needs live testing.

- [x] **Issue #687** — KiCad v7 octagonal pads render distorted — *Fixed 2026-06-19: `camlib.py` `ApertureMacro.default2zero(4, mods)` → `default2zero(6, mods)`*

- [x] **Issue #688** — Valid RS-274-X Gerber files rejected as "probably not a Gerber file" — *Fixed 2026-06-19: relaxed rejection condition to only fail when `buff_length == 0 AND area == 0`*

- [x] **Issue #605 / #505** — NCC "no NCC Geometry" errors — *Fixed 2026-06-19: guard `isinstance(solid_geometry, list)` before `.buffer(0)` in `ToolNCC.py`*

- [ ] **Issue #591** — Cutout multi-depth produces wrong output
  - Investigated: the `while depth > z_cut:` loop logic is correct — exits when depth equals z_cut. May be a user config issue; needs a reproduction case to confirm whether a real bug exists.

- [x] **Issue #604** — Tool moves XY before lifting to safe Z mid-job — *Fixed 2026-06-19: swapped order in `camlib.py` exclusion-zone traversal: lift Z at current position, then rapid XY*

- [ ] **Issue #682** — Cannot modify aperture size when DIM parameters exist
  - Aperture editing in the Gerber editor is blocked when the aperture has DIM parameters. `on_aptype_changed` not called with current index on init.

- [x] **Issue #526** — Milling target combo box defaults to first file, not selected object — *Fixed 2026-06-19: `blockSignals` around `target_radio.set_value` in `ToolMilling.set_tool_ui()`*

- [x] **Issue #528** — Extract Plugin source object selector jumps to wrong object — *Fixed 2026-06-19: `if obj and obj.kind == 'gerber':` guard in `ToolExtract.set_tool_ui()`*

- [x] **Issue #561** — `TclCommandMillDrills` doesn't parse tool list string correctly — *Fixed 2026-06-19: use `found_dias` set instead of decrement counter; fixed docstring example*

---

## Upstream PRs Worth Applying

- [ ] **PR #346** — Tool size validation: prevent milling when tool diameter = hole size
  - Safety fix — currently silently produces bad output. Should warn or abort. Author: Mike Evans.

- [ ] **PR #345** — Merge drilling tools when not all found in DB
  - Prevents phantom duplicate tools when multiple Excellon tools map to one DB entry. Author: Andrei Besfamilny.

- [ ] **PR #351** — Better slot-to-drill point distribution + TCL `drillcncjob` slot parity
  - Distributes slot drill points evenly along slot length. Makes TCL command match UI behavior. Author: phdussud. Also partially fixes #619.

- [ ] **PR #352** — Nearest-neighbor drill path optimization
  - Reduces traverse distance ~75% in examples. This fork already has OR-Tools optimization; compare both algorithms before merging. Author: Ben Buxton.

- [ ] **PR #127** — Open multiple Gerber/Excellon/G-code files at once in file dialog
  - QoL: currently must open files one at a time. Author: Travers Carter.

- [x] **PR #355 (partial)** — Two items relevant to this fork:
  - `int()` cast around `IndexToNode()` in `camlib.py` — *Fixed 2026-06-19*
  - `tclCommands/__init__.py` importlib modernization — *already done in prior session*

---

## Quality of Life

- [ ] **Issue #609** — SVG export only exports outermost isolation pass; inner passes missing
  - If you run 2-pass isolation and export SVG, only pass 1 appears. Check `export_svg` in `GeometryObject`.

- [x] **Issue #549** — No default preprocessor setting for Excellon jobs in Preferences — *Fixed 2026-06-19: `set_value` after `addItems` in `ToolsDrillPrefGroupUI.py`*

- [ ] **Issue #530** — Excellon editor: diameter change takes effect one click late
  - Off-by-one in the signal/slot wiring for the diameter spinbox.

- [ ] **Issue #504** — EasyEDA `.DRL` files not recognized (treated as non-Gerber)
  - EasyEDA exports a non-standard DRL header. Add detection to the Excellon parser.

- [ ] **Issue #413** — `drillcncjob` TCL command: toolchange Z height hardcoded at 0.1
  - Investigated: no hardcoded 0.1 found for toolchange Z. The `toolchangez` value reads from args or `options["tools_drill_toolchangez"]`. Likely already fixed or never a code bug.

- [x] **Issue #405** — Units displayed in wrong case ("5.4MM" instead of "5.4 mm") — *Already fixed: all preprocessors call `.lower()` on the units string*

- [x] **Issue #684** — No conda `environment.yml` — *Fixed 2026-06-19: `environment.yml` created with conda-forge packages including GDAL*

---

## Windows Installer

- [ ] Build a distributable Windows installer using **cx_Freeze + Inno Setup**
  - Runtime detection hooks (`sys.frozen`, `languages_dir_cx_freeze`) already in codebase
  - Template `setup_cx.py` and `flatcam.iss` documented in [INSTALLER.md](INSTALLER.md)
  - Key gotchas: VisPy private import in `appGUI/VisPyPatches.py`, preprocessors dynamic load path, OR-Tools native DLLs

---

## Verification Needed

These may already be fixed — confirm before spending time on them:

- [ ] **Issue #696** — NCC milling settings revert to wrong defaults on re-open. Jan 2024 changelog mentions NCC fixes; spot-check the NCC default-loading code.
- [ ] **Issue #567** — `check_zcut()` returns `None` → arithmetic crash. Current code at `camlib.py:3260` has returns in all branches. Test with `zcut=0` to confirm fixed.
- [ ] **Issue #532** — 1mm cutout gaps not generated in some configurations. Check `ToolCutOut` gap generation logic.
- [ ] **pikepdf 10.8.0 API** — requirement is `>=2.0`; pikepdf 10.x has changed some APIs. Test PDF import (`ToolPDF`) with a real multi-layer PDF before assuming it works.

---

## Previously Fixed (do not re-apply)

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
