import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_analysis import FakeLLM, start

from app.main import app
from app.models import ArchitectureHandoff, RequirementsApproval
from app.services.ollama import get_llm


@pytest.fixture
def llm(client):
    fake = FakeLLM()
    app.dependency_overrides[get_llm] = lambda: fake
    return fake


def ready(api):
    path = start(api)
    result = api.post(path + "/analyze", json={"expected_version": 2}).json()
    result = api.post(
        path + "/answers",
        json={
            "expected_version": result["project_version"],
            "answers": [{"question_id": "Q001", "value": "no"}],
        },
    ).json()
    assert result["state"] == "REQUIREMENTS_REVIEW"
    return path, result


def test_editorial_revisions_approval_freezes_exact_baseline(client, llm):
    api, engine = client
    path, result = ready(api)
    version = result["project_version"]
    for index in range(2):
        response = api.post(
            path + "/summary-revisions",
            json={
                "expected_version": version,
                "analysis_version": result["version"],
                "overview": "Reviewed portal overview",
                "review_notes": f"Notes {index}",
                "reviewer": "Customer",
            },
        )
        assert response.status_code == 201, response.text
        version += 1
    review = response.json()
    assert review["summary_revision"] == 2
    assert "Notes 0" not in review["markdown"]
    body = {
        "expected_version": version,
        "analysis_version": result["version"],
        "summary_revision": 1,
        "reviewer": "Customer",
        "confirm_business_understanding": True,
    }
    assert api.post(path + "/summary-approval", json=body).status_code == 409
    body["summary_revision"] = 2
    body["confirm_business_understanding"] = False
    assert api.post(path + "/summary-approval", json=body).status_code == 422
    body["confirm_business_understanding"] = True
    approved = api.post(path + "/summary-approval", json=body)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    assert api.get(path).json()["state"] == "AWAITING_ARCHITECTURE"
    assert "pending customer review" not in api.get(path + "/summary.md").text
    assert api.post(path + "/summary-approval", json=body).status_code == 409
    with Session(engine) as db:
        approval = db.scalar(select(RequirementsApproval))
        handoff = db.scalar(select(ArchitectureHandoff))
        assert handoff.status == "PENDING_INTEGRATION"
        assert handoff.payload["content_hash"] == approval.content_hash
        assert approval.snapshot["scope"] == "BUSINESS_REQUIREMENTS_ONLY"


def test_business_change_reopens_persisted_clarification_without_extraction(client, llm):
    api, _ = client
    path, result = ready(api)
    calls = len(llm.calls)
    response = api.post(
        path + "/summary-changes",
        json={
            "expected_version": result["project_version"],
            "analysis_version": result["version"],
            "feedback": "Add reporting for managers.",
            "related_requirement_ids": ["R001"],
        },
    )
    assert response.status_code == 200, response.text
    changed = response.json()
    assert changed["state"] == "AWAITING_CLARIFICATION"
    assert changed["summary"] is None
    assert len(llm.calls) == calls
    resumed = api.get(path + "/analysis").json()
    assert resumed["questions"][0]["id"] == "Q003"
    answered = api.post(
        path + "/answers",
        json={
            "expected_version": changed["project_version"],
            "answers": [{"question_id": "Q003", "value": "Managers need monthly sales reports."}],
        },
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["state"] == "REQUIREMENTS_REVIEW"
    assert len(llm.calls) == calls + 1


def test_blocked_summary_cannot_be_approved(client, llm):
    api, _ = client
    path = start(api)
    result = api.post(path + "/analyze", json={"expected_version": 2}).json()
    assert (
        api.post(
            path + "/summary-approval",
            json={
                "expected_version": result["project_version"],
                "analysis_version": result["version"],
                "summary_revision": 0,
                "reviewer": "Customer",
                "confirm_business_understanding": True,
            },
        ).status_code
        == 409
    )
