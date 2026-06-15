# FlatCAM Evo Beta — Project TODO
> Fork: colintrachte/flatcam (branch `mstanciu_Beta_8.995`)
> Based on Marius Stanciu's FlatCAM Evo Beta, itself a fork of jpcgt/flatcam
> Last reviewed: 2026-06-14

---

## HOW THE 8.994 WINDOWS INSTALLER WAS BUILT

The official 8.994 `.exe` installer was produced with **cx_Freeze**.  Evidence in the codebase:
- `appMain.py:580` — `# This will fail under cx_freeze ...`
- `appMain.py:586` — `# cx_freeze workaround`
- `appMain.py:3975` — `if getattr(sys, "frozen", False) is True:` (standard cx_freeze sentinel)
- `appMain.py:1560` — comment references `FlatCAM.exe (cx_freezed executable)`
- `appTranslation.py:80` — `def languages_dir_cx_freeze()` function

The workflow was:
1. `cx_Freeze` bundles Python + all packages + source into a `dist/FlatCAM/` folder
2. An installer tool (likely Inno Setup or NSIS) wraps that folder into a single `FlatCAM_8.994_Setup.exe`

The `setup.py` with cx_Freeze config was in the jpcgt Bitbucket repo (now inaccessible without auth).
All the runtime detection hooks are still present in this fork, so **cx_Freeze still works as a build path**.

### To build a Windows installer for this fork:
- **Option A (historical):** Write a `setup_cx.py` using cx_Freeze + wrap with Inno Setup (`flatcam.iss`)
- **Option B (modern):** Adapt `make_macos.py` from PR #355 to Windows using PyInstaller
- **Option C (current workaround):** The `setup_windows.ps1` + `run_flatcam.bat` we already have

---

## ENVIRONMENT STATUS (as of 2026-06-14)

| Component | Status |
|---|---|
| Python 3.12.10 | ✅ Used for `.venv` |
| PyQt6 6.11.0 | ✅ Installed, working |
| VisPy 0.16.2 | ✅ Working (private imports verified) |
| NumPy 2.4.6 | ✅ Working |
| Shapely 2.1.2 | ✅ Working |
| OR-Tools 9.15 | ✅ `pywrapcp` routing works |
| pikepdf 10.8.0 | ✅ Imports OK, needs runtime test |
| GDAL / rasterio | ❌ Not installed (needs Gohlke wheels) — Image import disabled |
| svgtrace / pyppeteer | ⚠️  Imports OK but pyppeteer is unmaintained — Chromium launch likely broken |

---

## BUGS ALREADY FIXED IN THIS FORK (do not re-apply)

- ✅ Tool-delete crash from 8.994 (`clicked_signal` NameError) — architecture fully rewritten
- ✅ Shapely 2.x `cap_style`/`join_style` API change
- ✅ NumPy `np.Inf` → `np.inf` deprecation
- ✅ Python 3.10 `collections.Iterable` removal
- ✅ UI thread-safety (calling Qt from worker threads)
- ✅ G-code end-move sequence (Z lifted before XY return) — correct in default + GRBL_11
- ✅ ezdxf Vec3/Vector alias — merged upstream
- ✅ TclCommandMillSlots fixes — merged upstream
- ✅ Python 3.10 system tray fix — merged upstream

## BUGS FIXED IN THIS SESSION

- ✅ JSON project save crash on `inf`/`nan` float values (`appHandlers/appIO.py`)
- ✅ Deprecated `SourceFileLoader.load_module()` in `appPreProcessor.py`
- ✅ Panelize while-loop: `columns`/`rows` could reach 0 under constrain mode (`appPlugins/ToolPanelize.py`)
- ✅ `FCLabel` used `QtCore.Signal` (PySide6-style) instead of `QtCore.pyqtSignal` — crashed startup (`appGUI/GUIElements.py`)

---

## DEPENDENCY ISSUES

### Broken / Will Break Soon

- [ ] **`pyppeteer` is abandoned** — last release 2022, uses Chromium r588429 which is years old and may not launch on modern Windows. It is used in `appPlugins/ToolImage.py` for SVG-to-bitmap tracing. At runtime, `check_chromium()` will try to download an old Chromium binary. **Fix:** Replace pyppeteer with `playwright` (already installed as a transitive dep) or remove the Chromium tracing path and rely on the `svgtrace` library's fallback.
  - Files: `appPlugins/ToolImage.py:27` — `from pyppeteer.chromium_downloader import check_chromium`

- [ ] **`svgtrace` depends on pyppeteer** — same issue as above. If pyppeteer's Chromium launch is broken, image tracing via Chromium fails silently.

- [ ] **`urllib3 1.26.20` is ancient** — urllib3 2.x has been out since 2023. Pinned old by pyppeteer's dependency resolution. When pyppeteer is removed, urllib3 can be updated.

- [ ] **`websockets 10.4` is old** — current is 14.x. Also a pyppeteer dependency.

- [ ] **`ortools>=7.0` requirement is stale** — 9.15 is installed and required. `requirements.txt` should say `ortools>=9.0`. The old API (`IndexToNode` returning int) works fine in 9.x.

### Loose / Should Be Tightened

- [ ] **`vispy>=0.9.0` is too loose** — We're on 0.16.2 and it works, but the constraint allows any future version. The private import `from vispy.app.backends._pyqt6 import CanvasBackendDesktop` in `appGUI/VisPyPatches.py` is fragile. Pin to `vispy>=0.9.0,<0.17` until the private import is removed or replaced.

- [ ] **`pyqt6>=6.1.0` is too loose** — 6.11.0 works but some signal APIs changed between versions. Consider `pyqt6>=6.4.0` as minimum (6.4 was a stability release).

### Missing from requirements.txt

- [ ] **`GDAL` / `rasterio`** need Windows-specific install instructions — the pip package tries to compile from source (fails without GDAL C headers). Add a comment pointing to https://github.com/cgohlke/geospatial-wheels for Windows.
  - Or add a `requirements-windows.txt` with pre-built wheel URLs.

- [ ] **`pywin32`** — mentioned in issue #489 as needed on Windows for some operations. Check if it's actually required.

### Can Be Removed / Replaced

- [ ] **`foronoi`** — listed as `# foronoi>=1.0.3` (commented out) in requirements.txt. Code in `ToolLevelling.py:44-45` is also commented out. Dead dependency — remove the comment entirely.

- [ ] **`pyqtdarktheme==1.1.1`** — also commented out in requirements.txt because the project bundles `libs/qdarktheme/` directly. This is intentional but undocumented. Add a comment explaining why it's bundled.

- [ ] **`six`** — Python 2/3 compatibility shim. Not needed in Python 3-only code. Installed as a transitive dep but listed in requirements.txt directly. Remove from requirements.txt.

---

## OPEN UPSTREAM PULL REQUESTS — APPLICABILITY TO THIS FORK

### High Priority — Apply

- [ ] **PR #352** — Nearest-neighbor drill path optimization (by Ben Buxton)
  - Reduces traverse distance ~75% in the example case (4401mm → 1101mm)
  - This fork already added path optimization options in March 2024, but uses a different algorithm
  - Worth comparing the two approaches and merging the better one
  - Branch: `shortest-drill-path`

- [ ] **PR #346** — Tool size validation: prevent milling when tool diameter = hole size
  - Safety fix — currently silently produces bad output (tool same size as hole = no material removed)
  - Author: Mike Evans, Branch: `Issue-240`

- [ ] **PR #345** — Merge drilling tools when not all found in DB
  - Prevents phantom duplicate tools when multiple excellon tools map to one DB entry
  - Author: Andrei Besfamilny

- [ ] **PR #351** — Better slot-to-drill point distribution + TCL `drillcncjob` slot parity
  - Distributes slot drill points more evenly along the slot length
  - Makes TCL command match UI behavior for slot conversion
  - Author: phdussud

### Medium Priority — Cherry-pick Selectively

- [ ] **PR #355** — macOS + Python 3.14 + NumPy 2.0 + VisPy 0.16 compat bundle
  - NumPy 2.0 `int()` cast for OR-Tools `IndexToNode()` (relevant — in `camlib.py:3008-3009`)
  - `importlib` modernization for `tclCommands/__init__.py` (we already fixed `appPreProcessor.py`)
  - macOS `.app` bundling via PyInstaller — adapt for Windows installer
  - Author: Ivan Marchand

- [ ] **PR #127** — Open multiple Gerber/Excellon/G-code files at once in file dialog
  - QoL improvement for importing batches of files
  - Author: Travers Carter

### Low Priority / Informational

- [ ] **PR #349** — Dockerfile for containerized FlatCAM
- [ ] **PR #305** — Sample TCL automation scripts with Makefile paths
- [ ] **PR #115** — Checkbox to toggle plot visibility of all objects together
- [ ] **PR #141** — SVG `getsvgtext` returning None vs empty list (minor correctness)

---

## OPEN UPSTREAM ISSUES — APPLICABLE TO THIS FORK

### Crashes (Blocker/Critical)

- [ ] **Issue #619** — App crashes when milling drill slots
  - Still present in Stanciu's Beta. PR #351 partially addresses this.
  - Investigate `ToolDrilling.process_slot_as_drills()` edge cases

- [ ] **Issue #567** — `camlib.check_zcut()` returns `None` → crash adding float to None
  - `check_zcut` missing a return statement → downstream arithmetic fails

- [ ] **Issue #500** — Corner markers crash on toggle in Gerber folder
  - Enabling/disabling corner markers causes AttributeError crash

- [ ] **Issue #529** — Gerber editor: Delete aperture button does nothing; Polygonize crashes editor window

### Major Functionality Broken

- [ ] **Issue #688** — Valid RS-274-X Gerber pads rejected as "probably not a Gerber file"
  - Specific Gerber files from KiCad export that work in other tools fail to load

- [ ] **Issue #687** — KiCad v7 octagonal pads render distorted

- [ ] **Issue #692** — Project save fails with CNC job — `inf`/`nan` in JSON (**FIXED this session**)

- [ ] **Issue #682** — Cannot modify aperture size when DIM parameters exist

- [ ] **Issue #475** — Panelize enters infinite loop on geometry/excellon objects (**PARTIALLY FIXED this session** — while-loop guard added)

- [ ] **Issue #591** — Cutout multi-depth produces wrong output

- [ ] **Issue #561** — `TclCommandMillDrills` doesn't parse tool list string correctly

- [ ] **Issue #539** — Isolation tool path offset inconsistency (critical for PCB accuracy)

- [ ] **Issue #528** — Extract Plugin source object selector jumps to wrong object

- [ ] **Issue #526** — Milling target combo box defaults to first file, not selected file

- [ ] **Issue #505** — NCC tool produces strange geometry in some configurations

- [ ] **Issue #605** — NCC generates "no NCC Geometry" errors with various tool diameters

### Quality of Life / Minor

- [ ] **Issue #696** — NCC milling settings revert to wrong defaults on re-open
  - Jan 2024 changelog mentions NCC fixes — may be partially addressed, needs verification

- [ ] **Issue #691** — GRBL_11 preprocessor missing `G21` (mm), `G90` (abs), `G94` (min feed) initialization lines
  - Small but matters: without these, some GRBL controllers may behave incorrectly on first run

- [ ] **Issue #684** — No conda environment file for Windows/Linux setup
  - A `environment.yml` would help users with conda (easier GDAL install via conda-forge)

- [ ] **Issue #625** — `make` Python version check fails for 3.11+ (Makefile version comparison logic is broken)

- [ ] **Issue #609** — SVG export only exports outermost isolation pass; inner passes missing

- [ ] **Issue #604** — Tool moves XY before lifting to safe travel height mid-job
  - Note: the *end-move* sequence is correct; this is about intermediate rapid moves

- [ ] **Issue #549** — No default preprocessor setting for Excellon jobs in Preferences

- [ ] **Issue #530** — Excellon editor: diameter change takes effect one click late

- [ ] **Issue #413** — `drillcncjob` TCL command: toolchange Z height not configurable (hardcoded 0.1)

- [ ] **Issue #405** — Units displayed in wrong case ("5.4MM" instead of "5.4 mm")

- [ ] **Issue #404** — Code quality: `appMain.py` is 8,000 lines; refactoring is ongoing but incomplete

- [ ] **Issue #504** — EasyEDA `.DRL` files not recognized (treated as non-Gerber)

### Windows-Specific

- [ ] **Issue #715** — No Windows installer for this fork
  - Build a cx_Freeze or PyInstaller installer (see installer section above)

- [ ] **Issue #489** — `requirements.txt` missing Windows-specific notes for GDAL/rasterio
  - Already handled in `setup_windows.ps1`, but requirements.txt needs comments

---

## WINDOWS INSTALLER TODO

- [ ] **Write `setup_cx.py`** — cx_Freeze configuration to bundle FlatCAM into `dist/FlatCAM/`
  - The runtime detection hooks (`sys.frozen`, `languages_dir_cx_freeze`) are already in the code
  - Need to include: `preprocessors/`, `tclCommands/`, `assets/`, `locale/`, `libs/`, `descartes/`
  - Exclude: `.venv/`, `.git/`, test files, `*.pyc`

- [ ] **Write `flatcam.iss`** — Inno Setup script to wrap `dist/FlatCAM/` into a one-file installer
  - Alternatively use NSIS (jpcgt may have used this; unable to confirm without accessing the 8.994 source)

- [ ] **Adapt PR #355's `make_macos.py` to Windows** using PyInstaller as an alternative build path
  - PyInstaller is simpler than cx_Freeze for one-file builds but produces larger binaries

---

## CODE QUALITY / MAINTENANCE

- [ ] **Remove or replace pyppeteer** — package is abandoned. Options:
  1. Replace with `playwright` (already installed, modern, maintained)
  2. Remove Chromium tracing path; keep only SVG/raster fallbacks in ToolImage
  3. Make the whole image-tracing feature conditional on Chromium availability

- [ ] **`appMain.py` refactoring** — ongoing (started March 2024). The file is 8,044 lines. The Edit menu methods were moved to `appEdit.py`. Continue moving handler groups out of appMain.

- [ ] **Fix Makefile Python version check** — the `min()` trick in Makefile breaks for 3.10+ vs 3.8 comparison. Needs a proper semver comparison or just remove the check.

- [ ] **Add `environment.yml`** for conda users — conda-forge has GDAL wheels that work on Windows, which solves the biggest install pain point.

- [ ] **Pin `vispy` more tightly** — change `vispy>=0.9.0` to `vispy>=0.9.0,<0.17` until private import fragility is resolved.

- [ ] **Update `ortools` minimum** — change `ortools>=7.0` to `ortools>=9.0` to match reality.

- [ ] **Remove `six` from requirements.txt** — it's a Python 2 compat shim, not needed here.

- [ ] **Document `libs/qdarktheme/`** — the bundled dark theme is intentional (avoids pyqtdarktheme version conflicts) but undocumented. Add a README or comment explaining why it's bundled rather than pip-installed.

---

## VERIFICATION NEEDED (may already be fixed, unconfirmed)

- [ ] **Issue #696** — NCC default values revert: CHANGELOG mentions NCC fixes in Jan 2024 — spot check the NCC default-loading code to confirm whether this is resolved
- [ ] **Issue #532** — 1mm cutout gaps not generated — check CutOut plugin gap generation logic
- [ ] **Issue #535** — Corner markers combo box + alignment — check ToolFiducials
- [ ] **pikepdf 10.8.0 API** — version requirements say `>=2.0`; pikepdf 10.x has had some API changes. Test PDF import (`ToolPDF`) with a real PDF file.
- [ ] **OR-Tools `IndexToNode` int cast** — PR #355 suggests adding explicit `int()` cast. `camlib.py:3008-3009`: `from_node = self.manager.IndexToNode(from_index)` — verify this doesn't cause issues with NumPy 2.x integer types.

---

## DONE / REFERENCE

| Date | What |
|---|---|
| 2026-06-14 | `setup_windows.ps1` created; `.venv` with Python 3.12 + all core deps working |
| 2026-06-14 | `FCLabel.QtCore.Signal` → `pyqtSignal` fixed (startup crash on PyQt6 6.x) |
| 2026-06-14 | JSON save `ignore_nan=True` added (project save crash with CNC job inf/nan values) |
| 2026-06-14 | `SourceFileLoader.load_module()` → modern `importlib.util` in `appPreProcessor.py` |
| 2026-06-14 | Panelize while-loop lower bound guard added |
| 2025-03-05 | Shapely 2.x buffer API strings |
| 2025-02-02 | NumPy `np.Inf` → `np.inf` |
| 2024-06-19 | SVG icon path fix |
| 2024-03-31 | Path optimization options added |
