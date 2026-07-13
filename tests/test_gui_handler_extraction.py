"""Parity tests for the Qt-free portion of the desktop CAM workflow."""

from pathlib import Path

from shapely.geometry import LineString, Polygon

from flatcam_core import count_vertex_points, simplify_tool_geometry, write_gcode


def test_count_vertex_points_handles_nested_geometry():
    polygon = Polygon(
        [(0, 0), (4, 0), (4, 4), (0, 4)],
        holes=[[(1, 1), (2, 1), (2, 2), (1, 2)]],
    )
    line = LineString([(0, 0), (1, 1), (2, 1)])

    assert count_vertex_points([[polygon], line]) == 13


def test_simplify_tool_geometry_does_not_mutate_source():
    line = LineString([(0, 0), (1, 0.01), (2, 0)])
    tools = {1: {"solid_geometry": [line], "data": {"name": "tool"}}}

    simplified, solid_geometry = simplify_tool_geometry(tools, tolerance=0.1)

    assert list(tools[1]["solid_geometry"][0].coords) == [(0, 0), (1, 0.01), (2, 0)]
    assert list(simplified[1]["solid_geometry"][0].coords) == [(0, 0), (2, 0)]
    assert solid_geometry.equals(simplified[1]["solid_geometry"][0])


def test_write_gcode_accepts_text_and_line_iterables(tmp_path: Path):
    text_path = tmp_path / "text.nc"
    lines_path = tmp_path / "lines.nc"

    write_gcode(text_path, "G00 X0\nG01 X1\n")
    write_gcode(lines_path, ["G00 X0\n", "G01 X1\n"])

    assert text_path.read_text() == "G00 X0\nG01 X1\n"
    assert lines_path.read_text() == text_path.read_text()


def test_write_gcode_can_force_windows_line_endings(tmp_path: Path):
    output = tmp_path / "windows.nc"

    write_gcode(output, "G00 X0\nG01 X1\n", force_windows_line_endings=True)

    assert output.read_bytes() == b"G00 X0\r\nG01 X1\r\n"
