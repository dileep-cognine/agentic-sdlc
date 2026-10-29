import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, WorkflowCheckpoint
from app.workflows.state import HUMAN_GATES, TRANSITIONS, WorkflowState, validate_transition


def test_intake_versions_conflicts_and_checkpoints(client):
    api, engine = client
    assert api.get("/health").json() == {"status": "ok"}
    response = api.post("/api/projects", json={"name": "Customer portal"})
    assert response.status_code == 201
    project = response.json()
    assert project["state"] == "INTAKE"
    path = f"/api/projects/{project['id']}/requirements"
    first = api.post(path, json={"text": "Users sign in\r\nsecurely", "expected_version": 1})
    assert first.status_code == 201
    assert first.json()["text"] == "Users sign in\nsecurely"
    assert api.post(path, json={"text": "stale", "expected_version": 1}).status_code == 409
    second = api.post(path, json={"text": "Updated requirements", "expected_version": 2})
    assert second.status_code == 201
    assert second.json()["requirement_id"] == first.json()["requirement_id"]
    assert second.json()["version"] == 2
    assert [r["version"] for r in api.get(path).json()] == [2, 1]
    current = api.get(f"/api/projects/{project['id']}").json()
    assert current["version"] == 3
    assert current["state"] == "INTAKE"
    assert len(api.get("/api/projects").json()) == 1
    with Session(engine) as db:
        checkpoints = list(
            db.scalars(select(WorkflowCheckpoint).order_by(WorkflowCheckpoint.project_version))
        )
        assert [c.project_version for c in checkpoints] == [1, 2, 3]
        assert checkpoints[-1].payload["requirement_version"] == 2


def test_validation_and_missing_projects(client):
    api, _ = client
    assert api.post("/api/projects", json={"name": "  "}).status_code == 422
    assert api.get("/api/projects/not-a-uuid").status_code == 422
    path = "/api/projects/00000000-0000-0000-0000-000000000000/requirements"
    assert api.get(path).status_code == 404
    project = api.post("/api/projects", json={"name": "Test"}).json()
    path = f"/api/projects/{project['id']}/requirements"
    for text in [" ", "x" * 100001]:
        response = api.post(path, json={"text": text, "expected_version": 1})
        assert response.status_code == 422
        assert response.json() == {"detail": "Invalid request data"}


def test_every_transition_and_human_gate():
    assert set(TRANSITIONS) == set(WorkflowState)
    for source in WorkflowState:
        for target in WorkflowState:
            if target not in TRANSITIONS[source] or (source, target) in HUMAN_GATES:
                with pytest.raises(ValueError):
                    validate_transition(source, target)
            else:
                validate_transition(source, target)
    for source, target in HUMAN_GATES:
        validate_transition(source, target, human_approved=True)


def test_submission_rejected_outside_intake(client):
    api, engine = client
    project = api.post("/api/projects", json={"name": "Test"}).json()
    with Session(engine) as db:
        stored = db.get(Project, project["id"])
        stored.state = WorkflowState.ANALYZING
        db.commit()
    response = api.post(
        f"/api/projects/{project['id']}/requirements",
        json={"text": "New text", "expected_version": 1},
    )
    assert response.status_code == 409
    assert api.get(f"/api/projects/{project['id']}").json()["version"] == 1
    with Session(engine) as db:
        assert len(list(db.scalars(select(WorkflowCheckpoint)))) == 1


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_local_dashboard_cors(client, origin):
    api, _ = client
    response = api.options(
        "/api/projects",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    response = api.post(
        "/api/projects", json={"name": "Browser project"}, headers={"Origin": origin}
    )
    assert response.status_code == 201
    assert response.headers["access-control-allow-origin"] == origin
