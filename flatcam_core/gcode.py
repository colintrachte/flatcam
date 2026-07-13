"""Qt-free G-code persistence helpers."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def write_gcode(
    filename: str | Path,
    source: str | Iterable[str],
    *,
    force_windows_line_endings: bool = False,
) -> None:
    """Write generated G-code using the desktop application's line policy."""
    newline = "\r\n" if force_windows_line_endings else None
    chunks = [source] if isinstance(source, str) else source
    with Path(filename).open("w", newline=newline) as output:
        output.writelines(chunks)
