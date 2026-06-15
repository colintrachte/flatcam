# Building a Windows Installer for FlatCAM Evo Beta

## Background: How 8.994 Was Built

The official FlatCAM 8.994 Windows installer was produced with **cx_Freeze**.
Evidence still present in this codebase:

| File | Line | Evidence |
|---|---|---|
| `appMain.py` | 580, 586 | `# This will fail under cx_freeze ...` / `# cx_freeze workaround` |
| `appMain.py` | 3975 | `if getattr(sys, "frozen", False) is True:` — standard cx_freeze/PyInstaller sentinel |
| `appMain.py` | 1560 | `# the args_to_process will contain the path to the FlatCAM.exe (cx_freezed executable)` |
| `appTranslation.py` | 80 | `def languages_dir_cx_freeze():` — locale path resolver for frozen builds |

The build workflow was:
1. `cx_Freeze` packages Python + all site-packages + FlatCAM source into `dist/FlatCAM/`
2. An installer builder (Inno Setup or NSIS) wraps `dist/FlatCAM/` into a single `FlatCAM_8.994_Setup.exe`

The `setup.py` with cx_Freeze configuration lived in jpcgt's Bitbucket repo and is
not directly accessible, but all the runtime detection hooks remain in this fork.

---

## Option A — cx_Freeze (Historical Path, Recommended)

### 1. Install build tools

```powershell
.venv\Scripts\python.exe -m pip install cx_Freeze
```

Download **Inno Setup** (free): https://jrsoftware.org/isdl.php

### 2. Create `setup_cx.py`

```python
from cx_Freeze import setup, Executable
import sys, os

# Files and directories that must ship with the app
include_files = [
    ("assets/",         "assets/"),
    ("config/",         "config/"),
    ("descartes/",      "descartes/"),
    ("libs/",           "libs/"),
    ("locale/",         "locale/"),
    ("preprocessors/",  "preprocessors/"),
    ("tclCommands/",    "tclCommands/"),
    ("appCommon/",      "appCommon/"),
    ("appEditors/",     "appEditors/"),
    ("appGUI/",         "appGUI/"),
    ("appHandlers/",    "appHandlers/"),
    ("appObjects/",     "appObjects/"),
    ("appParsers/",     "appParsers/"),
    ("appPlugins/",     "appPlugins/"),
]

build_exe_options = {
    "packages": [
        "PyQt6", "vispy", "shapely", "numpy", "matplotlib",
        "simplejson", "ezdxf", "rtree", "reportlab", "pikepdf",
        "qrcode", "pyserial", "lxml", "svg.path", "svglib",
        "fontTools", "freetype", "dill", "darkdetect",
        "ortools",
    ],
    "excludes": ["tkinter", "unittest", "email", "xml.etree"],
    "include_files": include_files,
    "include_msvcr": True,   # bundle VC++ runtime DLLs
    "build_exe": "dist/FlatCAM",
}

base = "Win32GUI" if sys.platform == "win32" else None

setup(
    name="FlatCAM Evo Beta",
    version="8.995",
    description="2D post-processing for PCB manufacturing",
    options={"build_exe": build_exe_options},
    executables=[
        Executable(
            "flatcam.py",
            base=base,
            target_name="FlatCAM.exe",
            icon="assets/resources/flatcam_icon256.ico",
        )
    ],
)
```

### 3. Build the distribution folder

```powershell
.venv\Scripts\python.exe setup_cx.py build_exe
```

Output: `dist/FlatCAM/FlatCAM.exe` + all dependencies

### 4. Create `flatcam.iss` for Inno Setup

```iss
[Setup]
AppName=FlatCAM Evo Beta
AppVersion=8.995
AppPublisher=Marius Stanciu
DefaultDirName={autopf}\FlatCAM
DefaultGroupName=FlatCAM
OutputBaseFilename=FlatCAM_8.995_Setup
OutputDir=installer_output
Compression=lzma2/ultra64
SolidCompression=yes
SetupIconFile=assets\resources\flatcam_icon256.ico
ArchitecturesInstallIn64BitMode=x64
MinVersion=6.1sp1

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "dist\FlatCAM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\FlatCAM"; Filename: "{app}\FlatCAM.exe"
Name: "{group}\Uninstall FlatCAM"; Filename: "{uninstallexe}"
Name: "{commondesktop}\FlatCAM"; Filename: "{app}\FlatCAM.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FlatCAM.exe"; Description: "Launch FlatCAM"; Flags: nowait postinstall skipifsilent
```

### 5. Compile the installer

Open Inno Setup IDE, load `flatcam.iss`, press F9.
Or from command line:

```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" flatcam.iss
```

Output: `installer_output\FlatCAM_8.995_Setup.exe`

---

## Option B — PyInstaller (Modern, Simpler)

PyInstaller produces a single-folder or single-file bundle. PR #355 used this for macOS.

### 1. Install

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
```

### 2. Generate spec file (first time only)

```powershell
cd d:\Git\flatcam
.venv\Scripts\pyinstaller --name FlatCAM --windowed --icon assets\resources\flatcam_icon256.ico flatcam.py
```

### 3. Edit `FlatCAM.spec` to add data files

```python
# In the Analysis() call, add:
datas=[
    ("assets",       "assets"),
    ("config",       "config"),
    ("descartes",    "descartes"),
    ("libs",         "libs"),
    ("locale",       "locale"),
    ("preprocessors","preprocessors"),
    ("tclCommands",  "tclCommands"),
],
hiddenimports=[
    "vispy.app.backends._pyqt6",
    "vispy.scene",
    "shapely",
    "rtree",
    "ortools.constraint_solver.pywrapcp",
    "ortools.constraint_solver.routing_enums_pb2",
    "PyQt6.sip",
],
```

### 4. Build

```powershell
.venv\Scripts\pyinstaller FlatCAM.spec
```

Output: `dist\FlatCAM\FlatCAM.exe`

Wrap with Inno Setup as in Option A steps 4-5.

---

## Option C — Current Working Method (No Installer)

The `setup_windows.ps1` script + `run_flatcam.bat` created in this session work now.
Suitable for developer use; not for end-user distribution.

```powershell
# One-time setup
.\setup_windows.ps1

# Daily use
.\run_flatcam.bat
```

---

## Known Issues for Frozen Builds

| Issue | Notes |
|---|---|
| **VisPy private import** | `from vispy.app.backends._pyqt6 import CanvasBackendDesktop` in `appGUI/VisPyPatches.py` — must be in `hiddenimports` for PyInstaller |
| **preprocessors loaded at runtime** | `appPreProcessor.py` dynamically loads all `preprocessors/*.py` files. In a frozen build the path changes; `languages_dir_cx_freeze()` in `appTranslation.py` already handles locale paths. The preprocessor path likely needs similar treatment. |
| **matplotlib cache** | PR #355 adds `matplotlib.use('Agg')` / cache config before Qt init in `flatcam.py` for PyInstaller builds |
| **OR-Tools native libs** | OR-Tools ships native `.so`/`.dll` files; must be included explicitly in cx_Freeze `packages` list |
| **GDAL** | If GDAL is installed, its native DLLs must be bundled. If not installed, ToolImage is already gracefully disabled. |
| **`sys.frozen` sentinel** | `appMain.py:3975` already checks `getattr(sys, "frozen", False)`. Both cx_Freeze and PyInstaller set this. |
| **Portable mode path** | In frozen cx_Freeze builds, `appMain.py:511` uses `os.path.dirname(os.path.dirname(os.path.realpath(__file__)))` as the config root. This resolves correctly relative to `FlatCAM.exe`. |

---

## Icon File

The icon at `assets/resources/flatcam_icon256.ico` — verify it exists or convert from `.png`:

```powershell
# Using Pillow to convert PNG to ICO
.venv\Scripts\python.exe -c "
from PIL import Image
img = Image.open('assets/resources/flatcam_icon256.png')
img.save('assets/resources/flatcam_icon256.ico', format='ICO', sizes=[(256,256),(128,128),(64,64),(32,32),(16,16)])
"
```

---

## Files to Add to .gitignore for Build Artifacts

```
/dist/
/build/
/installer_output/
/FlatCAM.spec
/setup_cx.py
/flatcam.iss
*.exe
```
