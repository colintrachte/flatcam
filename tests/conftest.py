import pytest
import flatcam_core.runner as _runner_mod

from flatcam_core import HeadlessAdapter, Project


@pytest.fixture()
def ctx():
    return HeadlessAdapter(config={"units": "mm"}, logger_name="test")


@pytest.fixture()
def project():
    return Project(name="test-project")


@pytest.fixture()
def clean_handlers(monkeypatch):
    """Reset the module-level handler registry for each test."""
    monkeypatch.setattr(_runner_mod, "_HANDLERS", {})
