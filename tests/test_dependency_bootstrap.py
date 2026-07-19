from types import SimpleNamespace

import appCommon.DependencyBootstrap as bootstrap


def test_missing_startup_dependencies_reports_only_unavailable_modules():
    missing = bootstrap.missing_startup_dependencies(
        find_spec=lambda name: None if name == "rasterio" else object()
    )

    assert missing == ["rasterio"]


def test_dependency_repair_runs_requirements_and_writes_marker(monkeypatch):
    repo_root = bootstrap.Path.cwd()
    requirements_path = repo_root / "requirements.txt"
    calls = []
    marker_writes = []
    import_checks = iter([["rasterio"], []])

    monkeypatch.setattr(bootstrap, "dependency_repair_needed", lambda *args: True)
    monkeypatch.setattr(bootstrap, "can_repair_current_environment", lambda: True)
    monkeypatch.setattr(
        bootstrap,
        "missing_startup_dependencies",
        lambda: next(import_checks),
    )
    monkeypatch.setattr(
        bootstrap.Path,
        "write_text",
        lambda self, value, encoding: marker_writes.append((self, value, encoding)),
    )

    def runner(command, cwd, check):
        calls.append((command, cwd, check))
        return SimpleNamespace(returncode=0)

    success, detail = bootstrap.repair_dependencies(repo_root, runner=runner)

    assert success is True
    assert detail == "dependencies installed"
    assert calls[0][0][-2:] == ["-r", str(requirements_path)]
    assert calls[0][1] == str(repo_root)
    assert marker_writes[0][1] == bootstrap.requirements_fingerprint(requirements_path)
    assert marker_writes[0][2] == "ascii"


def test_dependency_repair_does_not_modify_system_python(monkeypatch):
    monkeypatch.setattr(bootstrap, "missing_startup_dependencies", lambda: ["rasterio"])
    monkeypatch.setattr(bootstrap, "dependency_repair_needed", lambda *args: True)
    monkeypatch.setattr(bootstrap, "can_repair_current_environment", lambda: False)

    success, detail = bootstrap.repair_dependencies(bootstrap.Path.cwd())

    assert success is False
    assert "virtual environment" in detail
