import pytest
from shapely.geometry import Point, box

from flatcam_core import ShapelyGeometryEngine


@pytest.fixture()
def engine():
    return ShapelyGeometryEngine()


def test_offset_expands(engine):
    circle = Point(0, 0).buffer(1.0)
    result = engine.offset(circle, 0.5)
    assert result.area > circle.area


def test_offset_shrinks(engine):
    rect = box(0, 0, 10, 10)
    result = engine.offset(rect, -1.0)
    assert result.area < rect.area


def test_offset_join_style_round(engine):
    rect = box(0, 0, 5, 5)
    result = engine.offset(rect, 0.5, join_style="round")
    assert result.area > rect.area


def test_offset_join_style_flat(engine):
    rect = box(0, 0, 5, 5)
    result = engine.offset(rect, 0.5, join_style="flat")
    assert result.area > rect.area


def test_offset_join_style_square(engine):
    rect = box(0, 0, 5, 5)
    result = engine.offset(rect, 0.5, join_style="square")
    assert result.area > rect.area


def test_offset_int_passthrough(engine):
    # Legacy camlib callers pass integers; the engine must accept them.
    rect = box(0, 0, 5, 5)
    result = engine.offset(rect, 0.5, join_style=1)
    assert result.area > rect.area


def test_union_overlapping(engine):
    a = box(0, 0, 5, 5)
    b = box(4, 0, 9, 5)  # 1-unit overlap
    result = engine.union([a, b])
    assert result.area < a.area + b.area  # overlap counted once
    assert result.area > a.area           # bigger than either alone


def test_union_disjoint(engine):
    a = box(0, 0, 5, 5)
    b = box(10, 0, 15, 5)
    result = engine.union([a, b])
    assert abs(result.area - (a.area + b.area)) < 1e-9


def test_union_single(engine):
    a = box(0, 0, 5, 5)
    result = engine.union([a])
    assert abs(result.area - a.area) < 1e-9


def test_difference(engine):
    a = box(0, 0, 10, 10)
    b = box(0, 0, 5, 10)
    result = engine.difference(a, b)
    assert abs(result.area - 50.0) < 1e-9


def test_difference_no_overlap(engine):
    a = box(0, 0, 5, 5)
    b = box(10, 10, 15, 15)
    result = engine.difference(a, b)
    assert abs(result.area - a.area) < 1e-9


def test_intersection(engine):
    a = box(0, 0, 6, 6)
    b = box(4, 4, 10, 10)
    result = engine.intersection(a, b)
    assert abs(result.area - 4.0) < 1e-9


def test_intersection_no_overlap(engine):
    a = box(0, 0, 5, 5)
    b = box(10, 10, 15, 15)
    result = engine.intersection(a, b)
    assert result.is_empty


def test_simplify_reduces_coords(engine):
    circle = Point(0, 0).buffer(5.0, quad_segs=64)
    simplified = engine.simplify(circle, tolerance=0.5)
    assert len(simplified.exterior.coords) < len(circle.exterior.coords)


def test_simplify_large_tolerance_may_collapse(engine):
    rect = box(0, 0, 1, 1)
    result = engine.simplify(rect, tolerance=0.0)
    assert not result.is_empty


def test_repair_valid_geometry_unchanged(engine):
    rect = box(0, 0, 5, 5)
    result = engine.repair(rect)
    assert result.is_valid


def test_pocket_not_implemented(engine):
    rect = box(0, 0, 10, 10)
    with pytest.raises(NotImplementedError):
        engine.pocket(rect, tool_dia=0.5)
