import os

import pytest

from appCommon.StartupDiagnostics import diagnose_startup_exception


def test_graphics_failure_recommends_existing_2d_renderer():
    error = RuntimeError("OpenGL context creation returned no canvas")

    report = diagnose_startup_exception(
        error,
        "vispy.app.Canvas failed",
        stage_id="canvas",
        stage_title="Preparing the graphics canvas"
    )

    assert report.recovery_action == "restart_2d"
    assert "OpenGL" in report.likely_cause
    assert "2D compatibility" in report.recommended_action


def test_missing_dependency_names_module_without_claiming_graphics_failure():
    error = ModuleNotFoundError("No module named 'example_package'", name="example_package")

    report = diagnose_startup_exception(error, "import example_package")

    assert report.missing_module == "example_package"
    assert report.recovery_action == "copy_diagnostics"
    assert "example_package" in report.likely_cause


def test_preprocessor_failure_offers_one_run_safe_mode():
    error = RuntimeError("FlatCAMPostProcessor failed to register")

    report = diagnose_startup_exception(
        error,
        "custom preprocessor traceback",
        stage_id="preprocessors",
        stage_title="Loading preprocessors"
    )

    assert report.recovery_action == "restart_safe_mode"
    assert "user preprocessor" in report.likely_cause


def test_unknown_failure_preserves_uncertainty_and_traceback():
    error = ValueError("unexpected value")

    report = diagnose_startup_exception(error, "traceback evidence", "interface", "Building the interface")

    assert "could not determine an exact cause" in report.likely_cause
    assert "traceback evidence" in report.as_text()


def test_splash_tracks_stages_warnings_and_failure_actions(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    QtCore = pytest.importorskip("PyQt6.QtCore")
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    from appGUI.StartupSplash import StartupSplashScreen

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    splash = StartupSplashScreen(version="8.996")
    splash.set_stage("canvas", "Preparing the graphics canvas", "Starting the OpenGL renderer")

    assert splash.current_stage == "canvas"
    assert splash.progress.value() == 78
    assert splash.stage_rows["preferences"].property("stageState") == "done"
    assert splash.stage_rows["canvas"].property("stageState") == "active"

    splash.add_warning("Optional component unavailable", "GDAL missing", "Install GDAL if image import is needed.")
    assert splash.has_warnings is True
    assert "1 warning" in splash.warning_count_label.text()

    report = diagnose_startup_exception(
        RuntimeError("OpenGL context creation failed"),
        "vispy traceback",
        "canvas",
        "Preparing the graphics canvas"
    )
    QtCore.QTimer.singleShot(50, lambda: splash.action_requested.emit("exit"))
    assert splash.show_failure(report) == "exit"
    splash.close()
    app.processEvents()


def test_splash_has_four_rounded_corners_and_can_be_dragged(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    QtCore = pytest.importorskip("PyQt6.QtCore")
    QtGui = pytest.importorskip("PyQt6.QtGui")
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    from appGUI.StartupSplash import StartupSplashScreen

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    splash = StartupSplashScreen()
    splash.show()

    mask = splash.mask()
    assert not mask.contains(QtCore.QPoint(0, 0))
    assert not mask.contains(QtCore.QPoint(splash.width() - 1, 0))
    assert not mask.contains(QtCore.QPoint(0, splash.height() - 1))
    assert not mask.contains(QtCore.QPoint(splash.width() - 1, splash.height() - 1))
    assert mask.contains(splash.rect().center())

    original_position = splash.pos()
    press_position = splash.frameGeometry().topLeft() + QtCore.QPoint(40, 30)
    press_event = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        QtCore.QPointF(40, 30),
        QtCore.QPointF(press_position),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    move_event = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseMove,
        QtCore.QPointF(75, 52),
        QtCore.QPointF(press_position + QtCore.QPoint(35, 22)),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    release_event = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonRelease,
        QtCore.QPointF(75, 52),
        QtCore.QPointF(press_position + QtCore.QPoint(35, 22)),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    assert splash.eventFilter(splash.brand_panel, press_event) is True
    assert splash.eventFilter(splash.brand_panel, move_event) is True
    assert splash.eventFilter(splash.brand_panel, release_event) is True
    assert splash.pos() == original_position + QtCore.QPoint(35, 22)
    assert splash._drag_offset is None

    splash.close()
    app.processEvents()


def test_warning_actions_stay_visible_and_diagnostics_can_be_copied(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    QtCore = pytest.importorskip("PyQt6.QtCore")
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    from appGUI.StartupSplash import StartupSplashScreen

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    splash = StartupSplashScreen()
    long_recovery = "Review the dependency installation instructions. " * 14
    splash.add_warning(
        "Image Import plugin is unavailable",
        "ModuleNotFoundError: No module named 'rasterio'",
        long_recovery,
    )
    splash._show_warning_summary()
    app.processEvents()

    animation_offset = splash.board_widget._offset
    splash.board_widget._advance()
    assert splash.board_widget._offset != animation_offset
    assert splash.board_widget._timer.isActive()
    assert splash.board_widget._failed is False
    for button in (splash.continue_button, splash.copy_warning_button, splash.warning_log_button):
        top_left = button.mapTo(splash, QtCore.QPoint(0, 0))
        bottom_right = button.mapTo(splash, button.rect().bottomRight())
        assert splash.rect().contains(top_left)
        assert splash.rect().contains(bottom_right)
        assert button.isVisible()

    splash._copy_warning_diagnostics()
    clipboard_text = QtWidgets.QApplication.clipboard().text()
    assert "Image Import plugin is unavailable" in clipboard_text
    assert "No module named 'rasterio'" in clipboard_text
    assert splash.copy_warning_button.text() == "Diagnostics copied"

    splash.continue_button.click()
    assert splash._warnings_acknowledged is True

    splash.close()
    app.processEvents()


def test_generated_icon_sizes_match_resource_names():
    Image = pytest.importorskip("PIL.Image")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    resources = os.path.join(root, "assets", "resources")

    for size in (16, 24, 32, 48, 64, 128, 256):
        with Image.open(os.path.join(resources, "app%d.png" % size)) as image:
            assert image.size == (size, size)
            assert image.mode == "RGBA"
