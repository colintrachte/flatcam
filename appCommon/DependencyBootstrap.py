"""Repair a FlatCAM virtual environment before importing application modules."""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


REQUIRED_IMPORTS = (
    "PyQt6",
    "OpenGL",
    "cycler",
    "darkdetect",
    "dateutil",
    "dill",
    "ezdxf",
    "fastapi",
    "fontTools",
    "freetype",
    "kiwisolver",
    "lxml",
    "matplotlib",
    "numpy",
    "ortools",
    "pikepdf",
    "qrcode",
    "rasterio",
    "reportlab",
    "rtree",
    "serial",
    "shapely",
    "simplejson",
    "svg",
    "svglib",
    "uvicorn",
    "vispy",
)


def missing_startup_dependencies(find_spec=importlib.util.find_spec):
    """Return the startup dependencies that are not importable."""
    return [module_name for module_name in REQUIRED_IMPORTS if find_spec(module_name) is None]


def requirements_fingerprint(requirements_path):
    """Return a stable fingerprint for the active requirements file."""
    return hashlib.sha256(Path(requirements_path).read_bytes()).hexdigest()


def dependency_repair_needed(requirements_path, marker_path, missing_modules=None):
    """Check whether requirements changed or a startup dependency is absent."""
    if missing_modules is None:
        missing_modules = missing_startup_dependencies()
    if missing_modules:
        return True

    try:
        installed_fingerprint = Path(marker_path).read_text(encoding="ascii").strip()
    except OSError:
        return True
    return installed_fingerprint != requirements_fingerprint(requirements_path)


def can_repair_current_environment():
    """Only mutate a source checkout's virtual environment, never system Python."""
    return not getattr(sys, "frozen", False) and sys.prefix != sys.base_prefix


def repair_dependencies(repo_root, status_callback=None, runner=subprocess.run):
    """Install missing/changed requirements and return ``(success, detail)``."""
    requirements_path = Path(repo_root) / "requirements.txt"
    marker_path = Path(sys.prefix) / ".flatcam-requirements.sha256"
    missing_modules = missing_startup_dependencies()

    if not requirements_path.is_file():
        return False, "requirements.txt was not found"
    if not dependency_repair_needed(requirements_path, marker_path, missing_modules):
        return True, "dependencies are current"
    if not can_repair_current_environment():
        missing_text = ", ".join(missing_modules) or "requirements changed"
        return False, "automatic repair requires a virtual environment (%s)" % missing_text

    if status_callback is not None:
        status_callback(missing_modules)

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "-r",
        os.fspath(requirements_path),
    ]
    try:
        completed = runner(command, cwd=os.fspath(repo_root), check=False)
    except OSError as error:
        return False, "could not start pip: %s" % error
    if completed.returncode != 0:
        return False, "pip exited with status %d" % completed.returncode

    remaining = missing_startup_dependencies()
    if remaining:
        return False, "still missing after installation: %s" % ", ".join(remaining)

    try:
        marker_path.write_text(requirements_fingerprint(requirements_path), encoding="ascii")
    except OSError:
        # Installation succeeded. A missing marker only causes pip to recheck next launch.
        pass
    return True, "dependencies installed"
