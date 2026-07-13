from fastapi.testclient import TestClient

from flatcam_core import OperationKind, OperationResult, get_handler, register_handler
from flatcam_service import app


client = TestClient(app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_lists_core_operation_vocabulary():
    response = client.get("/v1/operations")

    assert response.status_code == 200
    assert "import_gerber" in response.json()["operations"]
    assert "export_gcode" in response.json()["operations"]
    assert "drill" not in response.json()["operations"]


def test_dry_run_returns_project_without_executing():
    response = client.post(
        "/v1/run",
        json={
            "name": "board",
            "dry_run": True,
            "documents": [
                {"id": "top", "name": "top.gbr", "source_path": "top.gbr"}
            ],
            "operations": [
                {"id": "import", "kind": "import_gerber", "inputs": ["top"]}
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["validation_errors"] == []
    assert body["project"]["name"] == "board"
    assert body["project"]["operations"]["import"]["status"] == "pending"


def test_dry_run_reports_core_validation_errors():
    response = client.post(
        "/v1/run",
        json={
            "dry_run": True,
            "operations": [{"kind": "isolation"}],
        },
    )

    assert response.status_code == 200
    assert "missing required params" in response.json()["validation_errors"][0]


def test_rejects_duplicate_ids():
    response = client.post(
        "/v1/run",
        json={
            "documents": [{"id": "same"}, {"id": "same"}],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Duplicate document id: same"


def test_reports_unknown_graph_inputs():
    response = client.post(
        "/v1/run",
        json={"operations": [{"id": "import", "kind": "import_gerber", "inputs": ["missing"]}]},
    )

    assert response.status_code == 200
    assert "unknown inputs" in response.json()["validation_errors"][0]


def test_reports_operation_cycles():
    response = client.post(
        "/v1/run",
        json={
            "operations": [
                {"id": "first", "kind": "import_gerber", "inputs": ["second"]},
                {"id": "second", "kind": "import_gerber", "inputs": ["first"]},
            ]
        },
    )

    assert response.status_code == 200
    assert any("cycle" in error for error in response.json()["validation_errors"])


def test_rejects_source_paths_outside_service_root(tmp_path):
    isolated_app = __import__("flatcam_service").create_app(tmp_path)
    response = TestClient(isolated_app).post(
        "/v1/run",
        json={"documents": [{"source_path": str(tmp_path.parent / "outside.gbr")}]},
    )

    assert response.status_code == 422
    assert "outside the service root" in response.json()["detail"]


def test_returns_structured_execution_results():
    def fail_handler(request, project, context):
        return OperationResult(status="error", error="deliberate failure")

    original = get_handler(OperationKind.IMPORT_GERBER)
    try:
        register_handler(OperationKind.IMPORT_GERBER, fail_handler)
        response = client.post(
            "/v1/run",
            json={"operations": [{"id": "import", "kind": "import_gerber"}]},
        )
    finally:
        register_handler(OperationKind.IMPORT_GERBER, original)

    assert response.status_code == 200
    assert response.json()["results"]["import"]["error"] == "deliberate failure"
