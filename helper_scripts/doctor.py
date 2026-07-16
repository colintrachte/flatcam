"""Read-only health checks for an installed Project Management Tools project.

Usage:
    python helper_scripts/doctor.py [PROJECT]
    python helper_scripts/doctor.py [PROJECT] --json

JSON schema v1 always contains: schema_version, project, kit_version, status, summary,
and checks. Checks are emitted in stable ID order and contain id, status, message, and
details. Exit status is 1 when any check is an error, otherwise 0. This command never
writes; repair behavior is deliberately out of scope.

The installed kit version and mechanics hash catalog come only from
helper_scripts/pmt_version.json. The unrelated .pmt-manifest.json schema_version is never
used as a kit version.
"""

import argparse
import ast
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import executor_registry  # noqa: E402
import route_tasks  # noqa: E402
from task_records import parse_tasks  # noqa: E402

TASK_ID_ANY_RE = re.compile(r"task_[0-9a-f]{32}")


@dataclass
class Check:
    id: str
    status: str
    message: str
    details: dict = field(default_factory=dict)

    def as_dict(self):
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _ok(check_id, message, **details):
    return Check(check_id, "ok", message, details)


def _error(check_id, message, **details):
    return Check(check_id, "error", message, details)


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run_checks(root: Path) -> dict:
    root = root.resolve()
    checks = []
    manifest_path = root / ".pmt-manifest.json"
    try:
        manifest = _load_json(manifest_path)
        if not isinstance(manifest.get("files"), dict):
            raise ValueError("files must be an object")
        manifest_schema = manifest.get("schema_version", 1)
        if not isinstance(manifest_schema, int):
            raise ValueError("schema_version must be an integer")
        for relative, record in manifest["files"].items():
            if not isinstance(relative, str) or not isinstance(record, dict):
                raise ValueError("manifest file records must be path/object pairs")
            for key in ("sha256", "template_sha256", "template", "installed_at"):
                if not isinstance(record.get(key), str) or not record[key]:
                    raise ValueError(f"{relative}: missing {key}")
        checks.append(
            _ok(
                "installation.manifest",
                "manifest is valid",
                schema_version=manifest_schema,
                managed_files=len(manifest["files"]),
            )
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        manifest = {"files": {}}
        checks.append(_error("installation.manifest", f"manifest is invalid: {exc}"))

    version_path = root / "helper_scripts" / "pmt_version.json"
    try:
        version = _load_json(version_path)
        kit_version = version["kit_version"]
        if version.get("schema_version") != 1 or not isinstance(kit_version, str):
            raise ValueError("unsupported version catalog")
        checks.append(
            _ok(
                "installation.version",
                f"installed kit version is {kit_version}",
                source="helper_scripts/pmt_version.json",
            )
        )
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        version = {"managed_mechanics": {}}
        kit_version = None
        checks.append(
            _error(
                "installation.version",
                f"kit version is unknown: {exc}",
                source="helper_scripts/pmt_version.json",
            )
        )

    stale = []
    for relative, expected in sorted(version.get("managed_mechanics", {}).items()):
        path = root / relative
        if not path.is_file() or digest(path) != expected:
            stale.append(relative)
    checks.append(
        _error(
            "installation.staleness", "installed mechanics differ from version catalog", paths=stale
        )
        if stale
        else _ok("installation.staleness", "installed mechanics match version catalog", paths=[])
    )

    python_errors = []
    python_paths = sorted(
        {root / relative for relative in manifest.get("files", {}) if relative.endswith(".py")}
        or set((root / "helper_scripts").glob("*.py"))
    )
    for path in python_paths:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            python_errors.append(f"{path.relative_to(root).as_posix()}: {exc}")
    checks.append(
        _error("dependencies.python_syntax", "Python syntax errors detected", errors=python_errors)
        if python_errors
        else _ok(
            "dependencies.python_syntax", "managed Python files parse", files=len(python_paths)
        )
    )

    roadmap = root / "docs" / "roadmap.md"
    shipped = root / "docs" / "shipped.md"
    try:
        lines = roadmap.read_text(encoding="utf-8").splitlines(keepends=True)
        task_lines = list(lines)
        if shipped.is_file():
            task_lines += shipped.read_text(encoding="utf-8").splitlines(keepends=True)
        ids = route_tasks.collect_task_ids(task_lines)
        # Active records must use the current identity/lifecycle contract. Historical
        # shipped prose predating that contract remains readable and need not be rewritten.
        i = 0
        while i < len(lines):
            if not route_tasks.TASK_RE.match(lines[i]):
                i += 1
                continue
            end = route_tasks.scan_block_end(lines, i + 1)
            block = lines[i:end]
            if route_tasks.task_id_of(block) is None:
                raise ValueError(f"{block[0].strip()}: missing permanent task ID")
            if route_tasks.task_status_of(block) is None:
                raise ValueError(f"{block[0].strip()}: missing lifecycle status")
            i = end
        tasks = parse_tasks(lines, root)
        first = route_tasks.process_roadmap(lines, roadmap, root)
        second = route_tasks.process_roadmap(first, roadmap, root)
        if first != second:
            raise ValueError("routing transform does not reach a fixed point")
        checks.append(
            _ok(
                "roadmap.round_trip",
                "roadmap parses and reaches a fixed point",
                open_tasks=len(tasks),
            )
        )
        checks.append(
            _ok(
                "roadmap.task_records", "task IDs and lifecycle fields are valid", task_ids=len(ids)
            )
        )
        drift = first != lines
        checks.append(
            _error("routing.annotations", "generated annotations are stale")
            if drift
            else _ok("routing.annotations", "generated annotations are current")
        )
        relationship_errors = route_tasks.validate_task_relationships(task_lines)
        checks.append(
            _error("dependencies.cycles", "dependency graph is invalid", errors=relationship_errors)
            if relationship_errors
            else _ok("dependencies.cycles", "dependency graph is valid")
        )
    except (OSError, ValueError, UnicodeError) as exc:
        ids, tasks = set(), []
        checks.extend(
            [
                _error("roadmap.round_trip", f"roadmap cannot be processed: {exc}"),
                _error("roadmap.task_records", f"task records are invalid: {exc}"),
                _error("routing.annotations", "annotation health is unknown"),
                _error("dependencies.cycles", "dependency health is unknown"),
            ]
        )

    # A missing Write target is the expected pre-task state, not a broken input.
    authored_outputs = {
        artifact["path"]
        for task in tasks
        for artifact in task.artifacts
        if artifact["role"] == "write"
    }
    missing = sorted(
        {
            raw
            for task in tasks
            for raw in task.missing
            if not route_tasks.external_ref_name(raw) and raw not in authored_outputs
        }
    )
    checks.append(
        _error("artifacts.paths", "listed artifacts are missing", paths=missing)
        if missing
        else _ok("artifacts.paths", "listed artifacts resolve", paths=[])
    )

    orphaned = []
    inbox = root / "helper_scripts" / "ai_inbox"
    if inbox.is_dir():
        for path in sorted(inbox.glob("*.md")):
            found = TASK_ID_ANY_RE.search(path.read_text(encoding="utf-8"))
            if not found or found.group(0) not in ids:
                orphaned.append(path.relative_to(root).as_posix())
    checks.append(
        _error("inbox.orphans", "orphaned inbox entries detected", paths=orphaned)
        if orphaned
        else _ok("inbox.orphans", "inbox entries map to task IDs", paths=[])
    )

    known_routes = set(executor_registry.load_registry().get("legacy_routes", []))
    obsolete = sorted(
        {
            task.route.split()[0]
            for task in tasks
            if task.route not in {"", "?"} and task.route.split()[0] not in known_routes
        }
    )
    checks.append(
        _error("routing.obsolete", "obsolete routes detected", routes=obsolete)
        if obsolete
        else _ok("routing.obsolete", "all routes are recognized", routes=[])
    )

    checks.sort(key=lambda item: item.id)
    errors = sum(item.status == "error" for item in checks)
    return {
        "schema_version": 1,
        "project": str(root),
        "kit_version": kit_version,
        "status": "error" if errors else "ok",
        "summary": {"checks": len(checks), "errors": errors},
        "checks": [item.as_dict() for item in checks],
    }


def render_human(result: dict) -> str:
    lines = [
        f"PMT doctor: {result['status'].upper()} — {result['project']}",
        f"Kit version: {result['kit_version'] or 'unknown'}",
    ]
    for check in result["checks"]:
        marker = "OK" if check["status"] == "ok" else "ERROR"
        lines.append(f"[{marker}] {check['id']}: {check['message']}")
    lines.append(f"{result['summary']['checks']} checks, {result['summary']['errors']} errors")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", type=Path, default=SCRIPT_DIR.parent)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_checks(args.project)
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else render_human(result))
    return 1 if result["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
