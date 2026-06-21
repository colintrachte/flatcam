from abc import ABC, abstractmethod
from typing import Any, List


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
