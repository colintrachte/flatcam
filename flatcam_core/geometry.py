from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Any, List, Mapping


class GeometryEngine(ABC):
    """Interface over the geometry backend.

    Current impl: ShapelyGeometryEngine (thin delegation to shapely).
    Future swap: replace with Clipper2/pyclipr impl in Stage 3 with zero
    call-site changes — the interface stays identical.
    """

    @abstractmethod
    def offset(self, geom: Any, distance: float, join_style: str = "round") -> Any:
        """Buffer outward (positive) or inward (negative)."""
        ...

    @abstractmethod
    def union(self, geoms: List[Any]) -> Any:
        """Return the unary union of a collection of geometries."""
        ...

    @abstractmethod
    def difference(self, a: Any, b: Any) -> Any:
        """Return a − b."""
        ...

    @abstractmethod
    def intersection(self, a: Any, b: Any) -> Any:
        """Return a ∩ b."""
        ...

    @abstractmethod
    def simplify(self, geom: Any, tolerance: float) -> Any:
        """Douglas-Peucker simplification."""
        ...

    @abstractmethod
    def repair(self, geom: Any) -> Any:
        """Make a geometry valid (fix self-intersections, etc.)."""
        ...

    @abstractmethod
    def pocket(self, geom: Any, tool_dia: float, overlap: float = 0.1) -> Any:
        """Generate pocket-fill toolpath geometry inside geom."""
        ...


class ShapelyGeometryEngine(GeometryEngine):
    """Delegates to the shapely backend already used by camlib.

    join_style strings map to shapely's legacy int constants so existing
    camlib call-sites that pass integers also work via .offset().
    """

    _JOIN: dict = {"round": 1, "flat": 2, "square": 3}

    def offset(self, geom: Any, distance: float, join_style: str = "round") -> Any:
        js = self._JOIN.get(join_style, join_style)  # accept int passthrough too
        return geom.buffer(distance, join_style=js)

    def union(self, geoms: List[Any]) -> Any:
        from shapely.ops import unary_union
        return unary_union(geoms)

    def difference(self, a: Any, b: Any) -> Any:
        from shapely import difference
        return difference(a, b)

    def intersection(self, a: Any, b: Any) -> Any:
        return a.intersection(b)

    def simplify(self, geom: Any, tolerance: float) -> Any:
        return geom.simplify(tolerance)

    def repair(self, geom: Any) -> Any:
        from shapely.validation import make_valid
        return make_valid(geom)

    def pocket(self, geom: Any, tool_dia: float, overlap: float = 0.1) -> Any:
        # Pocket-fill is in camlib.CNCjob (clear_polygon / clear_polygon2).
        # Wire through OperationRunner once camlib is on AppContext (Step 5).
        raise NotImplementedError(
            "pocket() not yet wired — implement via camlib.CNCjob.clear_polygon "
            "in OperationRunner (audit step 5)"
        )


def count_vertex_points(geometries: Any) -> int:
    """Count editable vertices in nested polygon and line geometry."""
    count = 0
    for geometry in _flatten_geometries(geometries):
        if geometry.geom_type == "Polygon":
            count += len(geometry.exterior.coords)
            count += sum(len(interior.coords) for interior in geometry.interiors)
        elif geometry.geom_type in {"LineString", "LinearRing"}:
            count += len(geometry.coords)
    return count


def simplify_tool_geometry(
    tools: Mapping[Any, Mapping[str, Any]], tolerance: float
) -> tuple[dict[Any, dict[str, Any]], Any]:
    """Return simplified tool data and its combined solid geometry.

    The input mapping is not mutated. This keeps the operation usable by both
    desktop handlers and non-GUI callers.
    """
    from shapely.ops import unary_union

    simplified_tools = deepcopy(dict(tools))
    all_geometry = []
    for tool in simplified_tools.values():
        geometry = _flatten_geometries(tool.get("solid_geometry", []))
        simplified = [shape.simplify(tolerance=tolerance) for shape in geometry]
        tool["solid_geometry"] = simplified
        all_geometry.extend(simplified)

    return simplified_tools, unary_union(all_geometry)


def _flatten_geometries(value: Any) -> list[Any]:
    """Flatten nested containers and Shapely multi-geometries."""
    if value is None:
        return []
    if hasattr(value, "geom_type"):
        if value.geom_type.startswith("Multi") or value.geom_type == "GeometryCollection":
            flattened = []
            for geometry in value.geoms:
                flattened.extend(_flatten_geometries(geometry))
            return flattened
        return [value]
    if isinstance(value, (str, bytes)):
        return []
    try:
        values = iter(value)
    except TypeError:
        return []

    flattened = []
    for item in values:
        flattened.extend(_flatten_geometries(item))
    return flattened
