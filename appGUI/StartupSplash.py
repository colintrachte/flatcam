import os
import time
from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from appCommon.StartupDiagnostics import StartupDiagnostic, StartupWarning


class CircuitBoardWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._offset = 0.0
        self._failed = False
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._advance)
        self._timer.start()
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_failed(self, failed):
        self._failed = bool(failed)
        if self._failed:
            self._timer.stop()
        elif not self._timer.isActive():
            self._timer.start()
        self.update()

    def _advance(self):
        self._offset = (self._offset + 1.2) % 24.0
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        grid_pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 24), 1)
        painter.setPen(grid_pen)
        for x_pos in range(16, self.width(), 52):
            painter.drawLine(x_pos, 0, x_pos, self.height())
        for y_pos in range(16, self.height(), 46):
            painter.drawLine(0, y_pos, self.width(), y_pos)

        trace_color = QtGui.QColor("#ef5350" if self._failed else "#d5a62c")
        trace_color.setAlpha(220)
        trace_pen = QtGui.QPen(trace_color, 2.4)
        trace_pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        trace_pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        trace_pen.setDashPattern([4.0, 3.0])
        trace_pen.setDashOffset(-self._offset)
        painter.setPen(trace_pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)

        width = max(self.width(), 1)
        height = max(self.height(), 1)
        paths = [
            [(0.02, 0.82), (0.22, 0.82), (0.22, 0.66), (0.42, 0.66), (0.42, 0.48),
             (0.64, 0.48), (0.64, 0.28), (0.98, 0.28)],
            [(0.02, 0.94), (0.30, 0.94), (0.30, 0.78), (0.52, 0.78), (0.52, 0.60),
             (0.78, 0.60), (0.78, 0.42), (0.98, 0.42)],
            [(0.04, 0.12), (0.28, 0.12), (0.28, 0.30), (0.50, 0.30), (0.50, 0.50),
             (0.72, 0.50), (0.72, 0.74), (0.98, 0.74)],
            [(0.16, 0.02), (0.16, 0.22), (0.38, 0.22), (0.38, 0.40), (0.60, 0.40),
             (0.60, 0.62), (0.88, 0.62), (0.88, 0.98)]
        ]
        for points in paths:
            path = QtGui.QPainterPath(QtCore.QPointF(points[0][0] * width, points[0][1] * height))
            for x_ratio, y_ratio in points[1:]:
                path.lineTo(x_ratio * width, y_ratio * height)
            painter.drawPath(path)

        pad_brush = QtGui.QBrush(QtGui.QColor("#173f46"))
        painter.setBrush(pad_brush)
        painter.setPen(QtGui.QPen(trace_color, 2.2))
        for x_ratio, y_ratio in ((.22, .66), (.42, .48), (.64, .28), (.30, .78), (.52, .60),
                                 (.78, .42), (.28, .30), (.50, .50), (.72, .74)):
            painter.drawEllipse(QtCore.QPointF(x_ratio * width, y_ratio * height), 5.0, 5.0)


class StageRow(QtWidgets.QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(10)

        self.marker = QtWidgets.QLabel()
        self.marker.setObjectName("stageMarker")
        self.marker.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.marker.setFixedSize(22, 22)
        layout.addWidget(self.marker)

        self.title = QtWidgets.QLabel(title)
        self.title.setObjectName("stageTitle")
        layout.addWidget(self.title, 1)

        self.detail = QtWidgets.QLabel("Queued")
        self.detail.setObjectName("stageDetail")
        layout.addWidget(self.detail)

        self.set_state("pending", 0)

    def set_state(self, state, number, detail=None):
        self.setProperty("stageState", state)
        self.marker.setProperty("stageState", state)
        self.title.setProperty("stageState", state)
        self.detail.setProperty("stageState", state)
        self.marker.setText("✓" if state == "done" else str(number))
        if detail is not None:
            self.detail.setText(detail)
        for widget in (self, self.marker, self.title, self.detail):
            widget.style().unpolish(widget)
            widget.style().polish(widget)


class StartupSplashScreen(QtWidgets.QWidget):
    action_requested = QtCore.pyqtSignal(str)

    STAGES = (
        ("preferences", "Preferences"),
        ("languages", "Languages"),
        ("preprocessors", "Preprocessors"),
        ("interface", "Interface"),
        ("canvas", "Canvas"),
        ("plugins", "Plugins")
    )

    STAGE_PROGRESS = {
        "bootstrap": 6,
        "preferences": 18,
        "languages": 32,
        "preprocessors": 46,
        "interface": 62,
        "canvas": 78,
        "plugins": 92,
        "ready": 100
    }

    def __init__(self, version="", log_path="", parent=None):
        flags = QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.version = version
        self.log_path = log_path
        self.current_stage = "bootstrap"
        self.current_stage_title = "Loading application modules"
        self._started_at = time.monotonic()
        self._stage_started_at = self._started_at
        self._stage_durations = {}
        self._warnings = []
        self._warnings_acknowledged = False
        self._wait_loop = None
        self._selected_action = "exit"
        self._primary_action = "copy_diagnostics"
        self._diagnostic_text = ""
        self._warning_diagnostic_text = ""
        self._finished = False
        self._drag_offset = None
        self._positioned = False

        self.setObjectName("startupSplash")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setFixedSize(760, 430)
        self._build_ui()
        self._apply_style()
        self._install_drag_handlers()
        self._update_window_mask()

        self._elapsed_timer = QtCore.QTimer(self)
        self._elapsed_timer.setInterval(100)
        self._elapsed_timer.timeout.connect(self._update_elapsed)
        self._elapsed_timer.start()

        self.action_requested.connect(self._complete_action)

    @property
    def has_warnings(self):
        return bool(self._warnings)

    def _build_ui(self):
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.brand_panel = QtWidgets.QFrame()
        self.brand_panel.setObjectName("brandPanel")
        self.brand_panel.setFixedWidth(302)
        brand_layout = QtWidgets.QVBoxLayout(self.brand_panel)
        brand_layout.setContentsMargins(28, 28, 22, 22)
        brand_layout.setSpacing(0)

        self.product_label = QtWidgets.QLabel("FlatCAM")
        self.product_label.setObjectName("productName")
        brand_layout.addWidget(self.product_label)

        self.edition_label = QtWidgets.QLabel(self._edition_text())
        self.edition_label.setObjectName("editionLabel")
        brand_layout.addWidget(self.edition_label)

        self.board_widget = CircuitBoardWidget()
        brand_layout.addWidget(self.board_widget, 1)

        self.brand_status = QtWidgets.QLabel("●  Core checks passing  ·  Python %s.%s" % (
            os.sys.version_info.major, os.sys.version_info.minor))
        self.brand_status.setObjectName("brandStatus")
        self.brand_status.setWordWrap(True)
        brand_layout.addWidget(self.brand_status)
        outer.addWidget(self.brand_panel)

        self.pages = QtWidgets.QStackedWidget()
        self.pages.setObjectName("startupPages")
        self.loading_page = self._build_loading_page()
        self.warning_page = self._build_warning_page()
        self.failure_page = self._build_failure_page()
        self.pages.addWidget(self.loading_page)
        self.pages.addWidget(self.warning_page)
        self.pages.addWidget(self.failure_page)
        outer.addWidget(self.pages, 1)

    def _build_loading_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 22)
        layout.setSpacing(12)

        header = QtWidgets.QHBoxLayout()
        header_text = QtWidgets.QVBoxLayout()
        header_text.setSpacing(3)
        eyebrow = QtWidgets.QLabel("STARTING WORKSPACE")
        eyebrow.setObjectName("eyebrow")
        self.stage_title_label = QtWidgets.QLabel(self.current_stage_title)
        self.stage_title_label.setObjectName("mainTitle")
        header_text.addWidget(eyebrow)
        header_text.addWidget(self.stage_title_label)
        header.addLayout(header_text, 1)
        self.elapsed_label = QtWidgets.QLabel("0.0 s")
        self.elapsed_label.setObjectName("elapsedLabel")
        header.addWidget(self.elapsed_label, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(self.STAGE_PROGRESS["bootstrap"])
        self.progress.setFixedHeight(5)
        layout.addWidget(self.progress)

        self.stage_rows = {}
        rows_layout = QtWidgets.QVBoxLayout()
        rows_layout.setSpacing(1)
        for index, (stage_id, title) in enumerate(self.STAGES, start=1):
            row = StageRow(title)
            row.set_state("pending", index)
            self.stage_rows[stage_id] = row
            rows_layout.addWidget(row)
        layout.addLayout(rows_layout)
        layout.addStretch(1)

        footer_line = QtWidgets.QFrame()
        footer_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        footer_line.setObjectName("footerLine")
        layout.addWidget(footer_line)
        footer = QtWidgets.QHBoxLayout()
        self.detail_label = QtWidgets.QLabel("Loading application modules…")
        self.detail_label.setObjectName("footerText")
        footer.addWidget(self.detail_label, 1)
        self.warning_count_label = QtWidgets.QLabel("")
        self.warning_count_label.setObjectName("warningCount")
        footer.addWidget(self.warning_count_label)
        layout.addLayout(footer)
        return page

    def _build_warning_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 22)
        layout.setSpacing(14)

        eyebrow = QtWidgets.QLabel("STARTUP CAN CONTINUE")
        eyebrow.setObjectName("warningEyebrow")
        layout.addWidget(eyebrow)
        title = QtWidgets.QLabel("FlatCAM started with a warning")
        title.setObjectName("mainTitle")
        layout.addWidget(title)
        self.warning_summary = QtWidgets.QLabel()
        self.warning_summary.setObjectName("bodyText")
        self.warning_summary.setWordWrap(True)
        layout.addWidget(self.warning_summary)
        self.warning_details = QtWidgets.QPlainTextEdit()
        self.warning_details.setObjectName("diagnosticDetails")
        self.warning_details.setReadOnly(True)
        layout.addWidget(self.warning_details, 1)
        self.warning_suggestion = QtWidgets.QPlainTextEdit()
        self.warning_suggestion.setObjectName("pathBox")
        self.warning_suggestion.setReadOnly(True)
        self.warning_suggestion.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.warning_suggestion.setMinimumHeight(58)
        self.warning_suggestion.setMaximumHeight(84)
        layout.addWidget(self.warning_suggestion)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(7)
        self.continue_button = QtWidgets.QPushButton("Continue startup")
        self.continue_button.setObjectName("primaryButton")
        self.continue_button.clicked.connect(self._acknowledge_warnings)
        buttons.addWidget(self.continue_button)
        self.copy_warning_button = QtWidgets.QPushButton("Copy diagnostics")
        self.copy_warning_button.clicked.connect(self._copy_warning_diagnostics)
        buttons.addWidget(self.copy_warning_button)
        self.warning_log_button = QtWidgets.QPushButton("Open log folder")
        self.warning_log_button.clicked.connect(self._open_log_folder)
        buttons.addWidget(self.warning_log_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return page

    def _build_failure_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(30, 26, 30, 18)
        layout.setSpacing(11)

        header = QtWidgets.QHBoxLayout()
        header_text = QtWidgets.QVBoxLayout()
        header_text.setSpacing(3)
        failure_eyebrow = QtWidgets.QLabel("STARTUP PAUSED")
        failure_eyebrow.setObjectName("failureEyebrow")
        self.failure_title = QtWidgets.QLabel("FlatCAM could not finish starting")
        self.failure_title.setObjectName("mainTitle")
        header_text.addWidget(failure_eyebrow)
        header_text.addWidget(self.failure_title)
        header.addLayout(header_text, 1)
        self.failure_elapsed = QtWidgets.QLabel("0.0 s")
        self.failure_elapsed.setObjectName("elapsedLabel")
        header.addWidget(self.failure_elapsed, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self.failure_cause = QtWidgets.QLabel()
        self.failure_cause.setObjectName("bodyText")
        self.failure_cause.setWordWrap(True)
        layout.addWidget(self.failure_cause)

        self.failure_evidence = QtWidgets.QLabel()
        self.failure_evidence.setObjectName("diagnosticBox")
        self.failure_evidence.setWordWrap(True)
        self.failure_evidence.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.failure_evidence)

        self.failure_recovery = QtWidgets.QLabel()
        self.failure_recovery.setObjectName("pathBox")
        self.failure_recovery.setWordWrap(True)
        layout.addWidget(self.failure_recovery)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(7)
        self.primary_button = QtWidgets.QPushButton("Copy diagnostics")
        self.primary_button.setObjectName("primaryButton")
        self.primary_button.clicked.connect(self._handle_primary_action)
        buttons.addWidget(self.primary_button)
        copy_button = QtWidgets.QPushButton("Copy diagnostics")
        copy_button.clicked.connect(self._copy_diagnostics)
        buttons.addWidget(copy_button)
        open_log_button = QtWidgets.QPushButton("Open log folder")
        open_log_button.clicked.connect(self._open_log_folder)
        buttons.addWidget(open_log_button)
        layout.addLayout(buttons)

        footer_line = QtWidgets.QFrame()
        footer_line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        footer_line.setObjectName("footerLine")
        layout.addWidget(footer_line)
        footer = QtWidgets.QHBoxLayout()
        hold_message = QtWidgets.QLabel("FlatCAM will remain open until you choose an action.")
        hold_message.setObjectName("footerText")
        footer.addWidget(hold_message, 1)
        exit_button = QtWidgets.QPushButton("Exit")
        exit_button.setObjectName("exitButton")
        exit_button.clicked.connect(lambda: self.action_requested.emit("exit"))
        footer.addWidget(exit_button)
        layout.addLayout(footer)
        return page

    def _apply_style(self):
        self.setStyleSheet("""
            QWidget#startupSplash {
                background: #f7f9fa;
                color: #263238;
                border: 1px solid #71838a;
                border-radius: 14px;
            }
            QFrame#brandPanel {
                background: #173f46;
                color: #f4f7f7;
                border-top-left-radius: 13px;
                border-bottom-left-radius: 13px;
            }
            QLabel#productName { color: #ffffff; font-size: 30px; font-weight: 500; }
            QLabel#editionLabel { color: #b7c9cc; font-size: 13px; }
            QLabel#brandStatus { color: #b7c9cc; font-size: 11px; }
            QStackedWidget#startupPages { background: #f7f9fa; }
            QLabel#eyebrow, QLabel#warningEyebrow, QLabel#failureEyebrow {
                color: #6d7d82; font-size: 11px; font-weight: 500;
            }
            QLabel#warningEyebrow { color: #a36a00; }
            QLabel#failureEyebrow { color: #b3261e; }
            QLabel#mainTitle { color: #18272c; font-size: 20px; font-weight: 500; }
            QLabel#elapsedLabel, QLabel#footerText, QLabel#stageDetail {
                color: #73858b; font-size: 11px;
            }
            QProgressBar { background: #dbe3e5; border: 0; border-radius: 2px; }
            QProgressBar::chunk { background: #2f7f8a; border-radius: 2px; }
            QLabel#stageMarker {
                color: #71838a; background: #f7f9fa; border: 1px solid #b7c4c8; border-radius: 11px;
            }
            QLabel#stageMarker[stageState="done"] {
                color: #ffffff; background: #2f7f8a; border-color: #2f7f8a;
            }
            QLabel#stageMarker[stageState="active"] {
                color: #ffffff; background: #173f46; border-color: #173f46;
            }
            QLabel#stageTitle { color: #708087; }
            QLabel#stageTitle[stageState="done"], QLabel#stageTitle[stageState="active"] { color: #263238; }
            QLabel#warningCount { color: #a36a00; font-size: 11px; }
            QFrame#footerLine { color: #d4dddf; }
            QLabel#bodyText { color: #33464c; font-size: 13px; }
            QLabel#diagnosticBox, QPlainTextEdit#diagnosticDetails {
                color: #33464c; background: #e9eff0; border: 0; border-radius: 6px; padding: 10px;
                font-family: "Cascadia Mono", Consolas, monospace; font-size: 11px;
            }
            QLabel#pathBox, QPlainTextEdit#pathBox {
                color: #263238; background: #e7eff0; border-left: 3px solid #2f7f8a; padding: 10px;
            }
            QPushButton {
                color: #24464c; background: #f7f9fa; border: 1px solid #9babb0; border-radius: 5px;
                padding: 7px 11px;
            }
            QPushButton:hover { background: #e8f0f1; }
            QPushButton#primaryButton {
                color: #ffffff; background: #173f46; border-color: #173f46; font-weight: 500;
            }
            QPushButton#primaryButton:hover { background: #245a63; }
            QPushButton#exitButton { border: 0; color: #6d7d82; }
        """)

    def _edition_text(self):
        return "Evo%s" % ("  ·  Beta %s" % self.version if self.version else "")

    def set_version(self, version):
        self.version = str(version)
        self.edition_label.setText(self._edition_text())
        self._process_events()

    def center_on_cursor_screen(self):
        screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
        if screen is None:
            screen = QtGui.QGuiApplication.primaryScreen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())

    def show(self):
        if not self._positioned:
            self.center_on_cursor_screen()
            self._positioned = True
        super().show()
        self._update_window_mask()
        self.raise_()
        self._process_events()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_window_mask()

    def _update_window_mask(self):
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(self.rect()).adjusted(0, 0, -1, -1), 14, 14)
        self.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))

    def _install_drag_handlers(self):
        self.installEventFilter(self)
        for widget in self.findChildren(QtWidgets.QWidget):
            widget.installEventFilter(self)

    @staticmethod
    def _is_interactive_drag_target(widget):
        if isinstance(widget, (QtWidgets.QAbstractButton, QtWidgets.QAbstractScrollArea,
                               QtWidgets.QLineEdit, QtWidgets.QComboBox)):
            return True
        return isinstance(widget, QtWidgets.QLabel) and (
            widget.textInteractionFlags() != QtCore.Qt.TextInteractionFlag.NoTextInteraction)

    def _begin_drag(self, global_position):
        self._drag_offset = global_position - self.frameGeometry().topLeft()

    def _drag_to(self, global_position):
        if self._drag_offset is not None:
            self.move(global_position - self._drag_offset)

    def _end_drag(self):
        self._drag_offset = None

    def eventFilter(self, watched, event):
        if self._is_interactive_drag_target(watched):
            return super().eventFilter(watched, event)

        event_type = event.type()
        if event_type == QtCore.QEvent.Type.MouseButtonPress and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._begin_drag(event.globalPosition().toPoint())
            return True
        if event_type == QtCore.QEvent.Type.MouseMove and self._drag_offset is not None:
            if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
                self._drag_to(event.globalPosition().toPoint())
                return True
        if event_type == QtCore.QEvent.Type.MouseButtonRelease and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._end_drag()
            return True
        return super().eventFilter(watched, event)

    def set_stage(self, stage_id, title, detail="", progress=None):
        now = time.monotonic()
        if self.current_stage != stage_id:
            self._stage_durations[self.current_stage] = now - self._stage_started_at
            self._stage_started_at = now
        self.current_stage = stage_id
        self.current_stage_title = title
        self.stage_title_label.setText(title)
        self.detail_label.setText(detail or title)
        self.progress.setValue(progress if progress is not None else self.STAGE_PROGRESS.get(stage_id, 0))
        self.pages.setCurrentWidget(self.loading_page)
        self.board_widget.set_failed(False)

        stage_ids = [item[0] for item in self.STAGES]
        active_index = stage_ids.index(stage_id) if stage_id in stage_ids else -1
        for index, row_stage in enumerate(stage_ids):
            row = self.stage_rows[row_stage]
            number = index + 1
            if active_index >= 0 and index < active_index:
                duration = self._stage_durations.get(row_stage)
                detail_text = "%.1f s" % duration if duration is not None else "Ready"
                row.set_state("done", number, detail_text)
            elif index == active_index:
                row.set_state("active", number, detail or "Working")
            else:
                row.set_state("pending", number, "Queued")
        self._process_events()

    def showMessage(self, message, alignment=None, color=None):
        if self._finished:
            return
        lines = [line.strip() for line in str(message).splitlines() if line.strip()]
        if lines:
            self.detail_label.setText(lines[-1])
        self._process_events()

    def add_warning(self, title, detail, suggestion):
        self._warnings.append(StartupWarning(str(title), str(detail), str(suggestion)))
        count = len(self._warnings)
        self.warning_count_label.setText("%d warning%s" % (count, "" if count == 1 else "s"))
        self.brand_status.setText("●  Startup warning recorded  ·  Python %s.%s" % (
            os.sys.version_info.major, os.sys.version_info.minor))
        self._process_events()

    def show_failure(self, diagnostic: StartupDiagnostic, log_path=""):
        self.log_path = log_path or self.log_path
        self._diagnostic_text = diagnostic.as_text()
        self._primary_action = diagnostic.recovery_action
        self.failure_title.setText(diagnostic.summary)
        self.failure_cause.setText("Most likely cause: %s\n\n%s" % (
            diagnostic.likely_cause, diagnostic.explanation))
        self.failure_evidence.setText(
            "Stage: %s\nException: %s" % (
                diagnostic.stage_title,
                diagnostic.technical_details.strip().splitlines()[-1] if diagnostic.technical_details.strip() else "Unknown"
            )
        )
        self.failure_recovery.setText("Recommended recovery\n%s" % diagnostic.recommended_action)
        labels = {
            "restart_2d": "Restart in 2D mode",
            "restart_safe_mode": "Restart in safe mode",
            "open_log": "Open log folder",
            "copy_diagnostics": "Copy diagnostics"
        }
        self.primary_button.setText(labels.get(self._primary_action, "Copy diagnostics"))
        self.failure_elapsed.setText("%.1f s" % (time.monotonic() - self._started_at))
        self.brand_status.setText("●  Startup paused safely  ·  Diagnostics preserved")
        self.board_widget.set_failed(True)
        self.pages.setCurrentWidget(self.failure_page)
        self._selected_action = "exit"
        self._wait_loop = QtCore.QEventLoop(self)
        self.show()
        self._wait_loop.exec()
        return self._selected_action

    def finish(self, target=None):
        if self._finished:
            return
        if self._warnings and not self._warnings_acknowledged:
            self._show_warning_summary()
            self._wait_loop = QtCore.QEventLoop(self)
            self._wait_loop.exec()
        self._finished = True
        self._elapsed_timer.stop()
        self.board_widget.set_failed(False)
        self.close()
        self._process_events()

    def _show_warning_summary(self):
        count = len(self._warnings)
        self.warning_summary.setText(
            "%d startup warning%s did not prevent the core workspace from loading." % (
                count, "" if count == 1 else "s"))
        details = []
        suggestions = []
        for warning in self._warnings:
            details.append("%s\n%s" % (warning.title, warning.detail))
            if warning.suggestion not in suggestions:
                suggestions.append(warning.suggestion)
        self.warning_details.setPlainText("\n\n".join(details))
        self.warning_suggestion.setPlainText("Suggested path\n%s" % "\n".join(suggestions))
        self._warning_diagnostic_text = "%s\n\n%s" % (
            "\n\n".join(details),
            "Suggested path\n%s" % "\n".join(suggestions)
        )
        self.copy_warning_button.setText("Copy diagnostics")
        self.pages.setCurrentWidget(self.warning_page)
        self.show()

    def _acknowledge_warnings(self):
        self._warnings_acknowledged = True
        if self._wait_loop is not None and self._wait_loop.isRunning():
            self._wait_loop.quit()

    def _handle_primary_action(self):
        if self._primary_action in ("restart_2d", "restart_safe_mode"):
            self.action_requested.emit(self._primary_action)
        elif self._primary_action == "open_log":
            self._open_log_folder()
        else:
            self._copy_diagnostics()

    def _copy_diagnostics(self):
        QtWidgets.QApplication.clipboard().setText(self._diagnostic_text)
        self.primary_button.setText("Diagnostics copied")

    def _copy_warning_diagnostics(self):
        QtWidgets.QApplication.clipboard().setText(self._warning_diagnostic_text)
        self.copy_warning_button.setText("Diagnostics copied")

    def _open_log_folder(self):
        folder = os.path.dirname(self.log_path) if self.log_path else ""
        if folder and os.path.isdir(folder):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))

    def _complete_action(self, action):
        self._selected_action = action
        if self._wait_loop is not None and self._wait_loop.isRunning():
            self._wait_loop.quit()

    def _update_elapsed(self):
        elapsed = time.monotonic() - self._started_at
        self.elapsed_label.setText("%.1f s" % elapsed)

    @staticmethod
    def _process_events():
        application = QtWidgets.QApplication.instance()
        if application is not None:
            application.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 20)


class NullStartupSplash:
    current_stage = "bootstrap"
    current_stage_title = "Loading application modules"
    has_warnings = False

    def set_version(self, version):
        pass

    def set_stage(self, stage_id, title, detail="", progress=None):
        self.current_stage = stage_id
        self.current_stage_title = title

    def showMessage(self, message, alignment=None, color=None):
        pass

    def add_warning(self, title, detail, suggestion):
        pass

    def finish(self, target=None):
        pass

    def show(self):
        pass

    def close(self):
        pass
