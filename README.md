# FlatCAM Evo Beta

2D post-processing for PCB manufacturing on CNC routers and laser cutters.

**Lineage:**
[Juan Pablo Caram](https://bitbucket.org/jpcgt/flatcam) (original FlatCAM)
→ [Marius Stanciu](https://bitbucket.org/marius_stanciu/flatcam_evo_beta) (FlatCAM Evo Beta, active upstream)
→ [dwrobel](https://github.com/dwrobel/flatcam) (Qt6 / modern Python port)
→ **this fork** (Windows-first maintenance branch)

FlatCAM takes Gerber and Excellon files from your PCB CAD tool and generates
G-code for isolation routing, drilling, milling, cutouts, and more.

---

## What this fork adds

- **`setup_windows.ps1`** — one-shot setup script that creates a Python virtual
  environment and installs all dependencies. Run it once, then double-click `run_flatcam.bat`.
- Bug fixes applied on top of upstream (see [TODO.md](TODO.md) for full list):
  - Project save crash when CNC jobs contained `inf`/`nan` float values
  - `FCLabel` startup crash on PyQt6 6.x (`Signal` → `pyqtSignal`)
  - Panelize column/row underflow when constrain area is smaller than one panel
  - Deprecated `SourceFileLoader.load_module()` replaced with modern `importlib.util`
- Updated `requirements.txt` with corrected version constraints and Windows GDAL notes
- Comprehensive [TODO.md](TODO.md) tracking all open upstream issues and PRs
- [INSTALLER.md](INSTALLER.md) documenting how to build a Windows installer with cx_Freeze

---

## Compatibility

| Component | Minimum | Tested |
|---|---|---|
| Python | 3.11 | **3.12.10** (recommended) |
| PyQt6 | 6.4.0 | 6.11.0 |
| VisPy | 0.9.0 | 0.16.2 |
| Shapely | 2.0 | 2.1.2 |
| NumPy | 1.16 | 2.4.6 |
| OR-Tools | 9.0 | 9.15 (optional) |

> **Python 3.14** may work but some C-extension wheels (VisPy, PyOpenGL, GDAL) may
> not yet have 3.14 builds. Use 3.12 if you encounter install failures.

---

## Windows — Quick Start

**Requirements:** Python 3.11 or 3.12 from [python.org](https://www.python.org/downloads/)

```powershell
# Clone the repo
git clone https://github.com/colintrachte/flatcam.git
cd flatcam

# Allow PowerShell to run local scripts (once, if not already set)
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# Create virtual environment and install all dependencies (~5 minutes)
.\setup_windows.ps1

# Launch FlatCAM
.\run_flatcam.bat
```

The setup script will:
1. Create `.venv/` with Python 3.12 (or 3.11 if 3.12 is not found)
2. Install all packages from `requirements.txt`
3. Attempt GDAL + rasterio (optional — see below)
4. Verify 8 key imports and report any failures
5. Write `run_flatcam.bat` for daily use

### GDAL / rasterio on Windows

These are only needed for the **Image Import** plugin (converting raster images to
PCB geometry). All other features work without them.

If the setup script's automatic install fails, download matching pre-built wheels from
[cgohlke/geospatial-wheels](https://github.com/cgohlke/geospatial-wheels/releases)
and install manually:

```powershell
.venv\Scripts\python.exe -m pip install GDAL-3.x.x-cp312-...-win_amd64.whl
.venv\Scripts\python.exe -m pip install rasterio-1.x.x-cp312-...-win_amd64.whl
```

### Subsequent runs

```powershell
.\run_flatcam.bat          # double-click works too
# or
.venv\Scripts\python.exe flatcam.py
```

---

## Linux — Quick Start

**Ubuntu / Debian:**

```bash
git clone https://github.com/colintrachte/flatcam.git
cd flatcam

# Install system packages (PyQt6, GDAL, etc.)
chmod +x setup_ubuntu.sh
sudo ./setup_ubuntu.sh

# Run
python3 flatcam.py
```

Or using Make:

```bash
# Install system packages
sudo make install_dependencies

# Install for current user only
make install

# System-wide
sudo make install
```

**Arch / Artix:**

```bash
# Install dependencies via pacman/AUR, then:
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 flatcam.py
```

**Conda (recommended for easy GDAL):**

```bash
conda create -n flatcam python=3.12
conda activate flatcam
conda install -c conda-forge gdal rasterio
pip install -r requirements.txt
python flatcam.py
```

---

## macOS

macOS support is experimental. PR #355 on the upstream repository contains a
`make_macos.py` script that builds a portable `.app` bundle using PyInstaller,
along with Shapely 2.x / NumPy 2.0 / VisPy 0.16 compatibility fixes.

Basic source install:

```bash
brew install python@3.12 gdal
git clone https://github.com/colintrachte/flatcam.git
cd flatcam
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python flatcam.py
```

---

## Windows Installer

No pre-built Windows installer is distributed from this fork yet.
See [INSTALLER.md](INSTALLER.md) for step-by-step instructions to build one
using cx_Freeze + Inno Setup (the same toolchain used for the official 8.994 release)
or PyInstaller as an alternative.

---

## Command-line options

```
flatcam.py --shellfile=<path>     Execute a Tcl script file at startup
flatcam.py --shellvar=<vars>      Pass variables to the Tcl shell
flatcam.py --headless=1           Run without GUI (for scripted batch jobs)
```

---

## Running headless (batch / CI)

```bash
python flatcam.py --headless=1 --shellfile=my_job.FlatScript
```

### HTTP service

Start the thin FastAPI adapter over `flatcam_core`:

```bash
python -m flatcam_service
```

The API listens on `http://127.0.0.1:8000`. Interactive documentation is at
`/docs`; `POST /v1/run` validates or executes a stateless project operation
graph, and `GET /v1/operations` lists operations with registered handlers.
Document paths are restricted to the current directory by default; set
`FLATCAM_SERVICE_ROOT` to choose another allowed input directory. Artifact data
is omitted unless the request sets `include_artifact_data` to `true`.

---

## Project structure

```
flatcam/
├── flatcam.py          Entry point
├── appMain.py          Core application class (~8 000 lines)
├── camlib.py           CAM geometry library (~8 500 lines)
├── appPlugins/         35 tools (isolation, NCC, drilling, panelize, …)
├── appParsers/         Gerber, Excellon, DXF, SVG, PDF, HPGL2 parsers
├── appEditors/         Gerber, Excellon, Geometry, G-code, text editors
├── appGUI/             PyQt6 UI components, VisPy canvas
├── appObjects/         Data model (Gerber, Excellon, Geometry, CNCJob, …)
├── appHandlers/        File I/O and edit operations
├── preprocessors/      28 G-code post-processors (GRBL, Marlin, Roland, …)
├── tclCommands/        76 Tcl scripting commands for batch automation
├── locale/             Translations: de en es fr it pt_BR ro ru tr zh
├── libs/qdarktheme/    Bundled dark/light theme (pinned version)
├── config/             Startup config (portable mode switch)
├── assets/             Icons, example scripts, stylesheets
├── requirements.txt    Python dependencies
├── setup_windows.ps1   Windows setup script (creates .venv)
├── setup_ubuntu.sh     Ubuntu/Debian system package installer
├── TODO.md             Tracked bugs, open PRs, dependency audit
└── INSTALLER.md        How to build a distributable Windows installer
```

---

## Optional features and their dependencies

| Feature | Requires | Notes |
|---|---|---|
| Image Import (raster → PCB) | GDAL, rasterio, svgtrace | Windows: needs Gohlke wheels |
| PDF Import | pikepdf | Installed by default |
| QR Code generation | qrcode | Installed by default |
| Path optimisation (TSP) | ortools | Installed by default; optional |
| Serial CNC control | pyserial | Installed by default |
| Dark / light theme | bundled libs/qdarktheme, darkdetect | No separate install needed |

---

## Known issues

See [TODO.md](TODO.md) for the full list. Notable items:

- **Slot drilling crash** — milling drill slots can crash in some Excellon files (upstream issue #619)
- **Gerber parsing** — some KiCad v7 Gerbers with octagonal pads render incorrectly (upstream #687)
- **NCC defaults** — Non-Copper Clear settings may revert on re-open (upstream #696)
- **Image tracing** — the `pyppeteer` library used for Chromium-based SVG tracing is abandoned;
  runtime image tracing via Chromium may not work. SVG and raster import paths still function.

---

## Upstream resources

- Upstream source: [bitbucket.org/jpcgt/flatcam](https://bitbucket.org/jpcgt/flatcam)
- Upstream issues: [bitbucket.org/jpcgt/flatcam/issues](https://bitbucket.org/jpcgt/flatcam/issues)
- Upstream pull requests: [bitbucket.org/jpcgt/flatcam/pull-requests](https://bitbucket.org/jpcgt/flatcam/pull-requests)
- Marius Stanciu's channel: [YouTube — FlatCAM tutorials](https://www.youtube.com/playlist?list=PLVvP2SYRpx-AQgNlfoxw93tXUXon7G94_)

---

## License

MIT — see [LICENSE](LICENSE)

Original FlatCAM © 2014–2018 Juan Pablo Caram
FlatCAM Evo Beta © 2019– Marius Stanciu
