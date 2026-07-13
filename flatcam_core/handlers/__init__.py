"""Built-in operation handlers for flatcam_core.runner.

Importing this package registers all three built-in handlers via the
``@handler(OperationKind.X)`` decorator in each sub-module.

Usage::

    import flatcam_core.handlers  # side-effect: registers handlers
    runner = OperationRunner(project, ctx)
    runner.run_all()
"""
from . import export_gcode, import_gerber, isolation  # noqa: F401 (side-effect imports)

__all__ = ["import_gerber", "isolation", "export_gcode"]
