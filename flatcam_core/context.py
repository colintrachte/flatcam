import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, Optional


@dataclass
class Event:
    """Structured event emitted by engine operations.

    type:    "progress" | "info" | "warning" | "error" | "success" | "done"
    source:  name of the operation that emitted this (e.g. "isolation")
    level:   "debug" | "info" | "warning" | "error"
    percent: 0-100 for progress events, None otherwise
    data:    arbitrary extra payload
    """

    type: str
    source: str
    level: str
    message: str
    percent: Optional[float] = None
    data: Dict[str, Any] = field(default_factory=dict)


class AppContext(ABC):
    """Runtime port — the single seam the engine depends on.

    All engine code accepts an AppContext instead of self.app.  Qt-desktop,
    headless service, CLI, and tests each provide a concrete adapter.

    Threading contract
    ------------------
    emit() MUST be thread-safe.  Handlers run in worker threads; the adapter
    is responsible for synchronisation.  HeadlessAdapter delegates to the
    stdlib logging module (thread-safe by design).  DesktopAdapter must route
    to Qt signals (also thread-safe when used correctly).  process_events() is
    always called from the engine thread — do not call it from the UI thread.
    cancel is a threading.Event and is safe to read/set from any thread.
    """

    # --- abstract members ---

    @property
    @abstractmethod
    def log(self) -> logging.Logger: ...

    @property
    @abstractmethod
    def cancel(self) -> threading.Event:
        """Per-job cancellation flag. Check inside long loops."""
        ...

    @property
    @abstractmethod
    def config(self) -> Mapping[str, Any]:
        """Read-only snapshot of application options (was self.app.options)."""
        ...

    @abstractmethod
    def emit(self, event: Event) -> None:
        """Deliver a structured event to the runtime (UI, WS stream, stdout…)."""
        ...

    @abstractmethod
    def process_events(self) -> None:
        """Allow the runtime to process pending events.

        Qt desktop: calls QApplication.processEvents().
        All other runtimes: no-op.
        """
        ...

    @abstractmethod
    def get_preprocessors(self) -> Dict[str, Any]:
        """Return the loaded preprocessor registry (was self.app.preprocessors)."""
        ...

    # --- convenience helpers (map legacy camlib inform patterns) ---

    def inform(self, message: str, *, source: str = "") -> None:
        """Emit a text notification, inferring level from the legacy prefix."""
        msg_upper = message.upper()
        if "[ERROR" in msg_upper:
            level, etype = "error", "error"
        elif "[WARNING" in msg_upper:
            level, etype = "warning", "warning"
        elif "[SUCCESS]" in msg_upper:
            level, etype = "info", "success"
        else:
            level, etype = "info", "info"
        self.emit(Event(type=etype, source=source, level=level, message=message))

    def progress(
        self,
        text: str,
        percent: Optional[float] = None,
        *,
        source: str = "",
    ) -> None:
        """Emit a progress update (was self.app.proc_container.update_view_text)."""
        self.emit(Event(
            type="progress",
            source=source,
            level="info",
            message=text,
            percent=percent,
        ))


class HeadlessAdapter(AppContext):
    """Concrete AppContext for non-Qt use: CLI, tests, background service.

    Instantiate once per job so the cancel flag is isolated:
        ctx = HeadlessAdapter(config=snapshot, logger_name="job-42")
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        logger_name: str = "flatcam_core",
        cancel: Optional[threading.Event] = None,
        preprocessors: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._log = logging.getLogger(logger_name)
        self._cancel = cancel if cancel is not None else threading.Event()
        # MappingProxyType prevents handlers from mutating the per-request config.
        self._config: Mapping[str, Any] = MappingProxyType(
            config if config is not None else {}
        )
        self._preprocessors: Dict[str, Any] = (
            preprocessors if preprocessors is not None else {}
        )

    @property
    def log(self) -> logging.Logger:
        return self._log

    @property
    def cancel(self) -> threading.Event:
        return self._cancel

    @property
    def config(self) -> Mapping[str, Any]:
        return self._config

    def emit(self, event: Event) -> None:
        lvl = getattr(logging, event.level.upper(), logging.INFO)
        self._log.log(
            lvl,
            "[%s] %s",
            event.source or "core",
            event.message,
        )

    def process_events(self) -> None:
        pass

    def get_preprocessors(self) -> Dict[str, Any]:
        return self._preprocessors
