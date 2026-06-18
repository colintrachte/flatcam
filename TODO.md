# FlatCAM Evo Beta — TODO
> Fork: colintrachte/flatcam (branch `mstanciu_Beta_8.995`)
> Last reviewed: 2026-06-17

---

## Critical Crashes

- [ ] **Issue #619** — App crashes when milling drill slots
  - PR #351 partially addresses this (better slot-to-drill distribution). Investigate `ToolDrilling.process_slot_as_drills()` edge cases independently.

- [ ] **Issue #500** — Corner markers crash on toggle in Gerber folder
  - Enabling/disabling corner markers causes AttributeError. Check `ToolFiducials`.

- [ ] **Issue #529** — Gerber editor: Delete aperture button does nothing; Polygonize crashes the editor
  - Two separate bugs in the Gerber editor, both block editing workflows.

---

## Major PCB Workflow Bugs

- [ ] **Issue #539** — Isolation tool path offset inconsistency
  - Critical for PCB accuracy: the offset applied during isolation routing is not consistent across all pass counts. Check `ToolIsolation`.

- [ ] **Issue #687** — KiCad v7 octagonal pads render distorted
  - Octagonal apertures from KiCad v7 Gerber export are not drawn correctly.

- [ ] **Issue #688** — Valid RS-274-X Gerber files rejected as "probably not a Gerber file"
  - Legal Gerber files that other tools load fine fail here. Gerber parser is over-strict.

- [ ] **Issue #605 / #505** — NCC "no NCC Geometry" errors and strange geometry in some configurations
  - Two related reports. NCC fails silently or produces incorrect fill geometry with certain tool diameters and overlap settings.

- [ ] **Issue #591** — Cutout multi-depth produces wrong output
  - Multi-pass cutout (`z_depthpercut`) generates incorrect G-code depth sequence.

- [ ] **Issue #604** — Tool moves XY before lifting to safe Z mid-job
  - Rapid moves between cuts drag the tool through material. The end-move is correct; this is intermediate rapids. Check gcode generation in `camlib.py`.

- [ ] **Issue #682** — Cannot modify aperture size when DIM parameters exist
  - Aperture editing in the Gerber editor is blocked when the aperture has DIM parameters.

- [ ] **Issue #526** — Milling target combo box defaults to first file, not selected object
  - When you open Milling, the source object should pre-select whatever is active in the project list.

- [ ] **Issue #528** — Extract Plugin source object selector jumps to wrong object
  - Source selector in the Extract plugin does not track the currently selected object.

- [ ] **Issue #561** — `TclCommandMillDrills` doesn't parse tool list string correctly
  - TCL batch users cannot specify multiple tools; the string parser splits wrong.

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

- [ ] **PR #355 (partial)** — Two items relevant to this fork:
  - Add explicit `int()` cast around `IndexToNode()` in `camlib.py:3008-3009` (NumPy 2.x integer type compatibility)
  - Modernize `tclCommands/__init__.py` with `importlib.util` (same fix already applied to `appPreProcessor.py`)

---

## Quality of Life

- [ ] **Issue #609** — SVG export only exports outermost isolation pass; inner passes missing
  - If you run 2-pass isolation and export SVG, only pass 1 appears. Check `export_svg` in `GeometryObject`.

- [ ] **Issue #549** — No default preprocessor setting for Excellon jobs in Preferences
  - Excellon jobs default to the geometry preprocessor; should have its own preference entry.

- [ ] **Issue #530** — Excellon editor: diameter change takes effect one click late
  - Off-by-one in the signal/slot wiring for the diameter spinbox.

- [ ] **Issue #504** — EasyEDA `.DRL` files not recognized (treated as non-Gerber)
  - EasyEDA exports a non-standard DRL header. Add detection to the Excellon parser.

- [ ] **Issue #413** — `drillcncjob` TCL command: toolchange Z height hardcoded at 0.1
  - Should respect the preference value; currently ignores it.

- [ ] **Issue #405** — Units displayed in wrong case ("5.4MM" instead of "5.4 mm")
  - Cosmetic but appears in generated G-code comments.

- [ ] **Issue #684** — No conda `environment.yml`
  - conda-forge has working GDAL wheels; an `environment.yml` is the easiest install path for new users who want image import.

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
| 2026-06-17 | Misspellings fixed across 14 files (`toogle`, `curent`, `overriden`, `rectange`, `lenghtx`/`lenghty`, etc.) |
| 2026-06-17 | Default G-code save extension changed from `.nc` to `.gcode` |
| 2026-06-17 | Legacy project blocking dialog removed; replaced with non-blocking status-bar warning |
| 2026-06-14 | `FCLabel` startup crash: `QtCore.Signal` → `pyqtSignal` |
| 2026-06-14 | JSON project save crash on `inf`/`nan` float values (`appHandlers/appIO.py`) |
| 2026-06-14 | Panelize while-loop underflow (columns/rows reaching 0 under constrain mode) |
| 2026-06-14 | `SourceFileLoader.load_module()` → `importlib.util` in `appPreProcessor.py` |
| 2026-06-14 | `requirements.txt` cleaned: vispy pinned `<0.17`, `ortools>=9.0`, `six` removed, GDAL noted |
| Before fork | Tool-delete crash (8.994), Shapely 2.x API, NumPy deprecations, thread-safety, GRBL_11 G21/G90/G94 |
