from copy import deepcopy

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis_schemas import AnalysisDocument, Answer, Usage
from app.main import app
from app.models import AnalysisVersion, GraphRuntime, WorkflowCheckpoint
from app.services.ollama import LLMError, get_llm
from app.services.validation import question_batch, required_questions, validate_answers


def document():
    return {
        "overview": "A customer portal.",
        "requirements": [
            {
                "id": "R001",
                "category": "functional",
                "text": "Customers sign in.",
                "origin": "stated",
                "source_refs": ["S1"],
            },
            {
                "id": "R002",
                "category": "non_functional",
                "text": "Security decision is undecided.",
                "origin": "assumption",
                "source_refs": [],
            },
        ],
        "gaps": [
            {
                "kind": "security",
                "description": "MFA decision missing.",
                "related_requirement_ids": ["R002"],
                "question_ids": ["Q001"],
            }
        ],
        "questions": [
            {
                "id": "Q001",
                "text": "Require MFA?",
                "type": "yes_no",
                "options": ["yes", "no"],
                "related_requirement_ids": ["R002"],
                "blocking": True,
                "priority": 1,
                "condition": None,
            },
            {
                "id": "Q002",
                "text": "Which MFA method?",
                "type": "single_select",
                "options": ["TOTP", "Hardware key"],
                "related_requirement_ids": ["R002"],
                "blocking": True,
                "priority": 2,
                "condition": {"question_id": "Q001", "any_of": ["yes"]},
            },
        ],
    }


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.initial = document()

    def check(self):
        return {"status": "ok"}

    def generate(self, schema, instructions, payload):
        self.calls.append(deepcopy(payload))
        if self.fail:
            raise LLMError("unavailable", "Remote Ollama unreachable", 503)
        if schema is AnalysisDocument:
            value = self.initial
        else:
            requirements = []
            for r in payload["requirements"]:
                related = [
                    c
                    for c in payload["clarifications"]
                    if r["id"] in c["question"]["related_requirement_ids"]
                ]
                requirements.append(
                    {
                        "id": r["id"],
                        "text": "Customer decision: "
                        + "; ".join(str(c["answer"]) for c in related),
                        "resolved_category": "non_functional"
                        if r["category"] == "assumption"
                        else None,
                    }
                )
            value = {"requirements": requirements}
        return schema.model_validate(value), Usage(
            input_tokens=10, output_tokens=20, latency_ms=1, attempts=1
        )


@pytest.fixture
def llm(client):
    fake = FakeLLM()
    app.dependency_overrides[get_llm] = lambda: fake
    return fake


def start(api):
    project = api.post("/api/projects", json={"name": "Portal"}).json()
    path = f"/api/projects/{project['id']}"
    assert (
        api.post(
            path + "/requirements", json={"text": "Customers sign in.", "expected_version": 1}
        ).status_code
        == 201
    )
    return path


def test_persistent_interrupt_resume_edit_and_versions(client, llm):
    api, engine = client
    path = start(api)
    result = api.post(path + "/analyze", json={"expected_version": 2})
    assert result.status_code == 200, result.text
    initial = result.json()
    assert initial["state"] == "AWAITING_CLARIFICATION"
    assert [q["id"] for q in initial["questions"]] == ["Q001"]
    assert initial["summary"] is None
    with Session(engine) as db:
        assert db.get(GraphRuntime, initial["project_id"]).payload["checkpoints"]
    # Every request constructs a NEW graph and saver from persisted SQL state.
    first = api.post(
        path + "/answers",
        json={
            "expected_version": initial["project_version"],
            "answers": [{"question_id": "Q001", "value": "yes"}],
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["questions"][0]["id"] == "Q002"
    second = api.post(
        path + "/answers",
        json={
            "expected_version": first.json()["project_version"],
            "answers": [{"question_id": "Q002", "value": "TOTP"}],
        },
    )
    assert second.status_code == 200, second.text
    review = second.json()
    assert review["state"] == "REQUIREMENTS_REVIEW"
    assert review["summary"]["status"] == "DRAFT"
    assert "TOTP" in review["markdown"]
    assert review["document"]["requirements"][0] == initial["document"]["requirements"][0]
    assert "sources" not in llm.calls[1] and len(llm.calls[1]["requirements"]) == 1
    assert llm.calls[1]["requirements"][0]["id"] == "R002"
    edited = api.post(
        path + "/answers",
        json={
            "expected_version": review["project_version"],
            "answers": [{"question_id": "Q001", "value": "no"}],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["state"] == "REQUIREMENTS_REVIEW"
    assert edited.json()["answers"] == {"Q001": "no"}
    assert "TOTP" not in edited.json()["markdown"]
    assert edited.json()["version"] == 4
    old = api.get(path + "/analysis?version=3").json()
    assert old["answers"]["Q002"] == "TOTP"
    assert len(api.get(path + "/analysis/versions").json()) == 4
    assert len(api.get(path + "/answers/history").json()) == 3
    assert api.get(path + "/summary.md").status_code == 200
    with Session(engine) as db:
        assert len(list(db.scalars(select(AnalysisVersion)))) == 4
        assert len(list(db.scalars(select(WorkflowCheckpoint)))) == 10


def test_invalid_answers_and_stale_version_are_atomic(client, llm):
    api, engine = client
    path = start(api)
    initial = api.post(path + "/analyze", json={"expected_version": 2}).json()
    for answers in [
        [{"question_id": "Q001", "value": "maybe"}],
        [{"question_id": "Q002", "value": "TOTP"}],
        [{"question_id": "Q001", "value": "yes"}] * 2,
    ]:
        result = api.post(
            path + "/answers",
            json={"expected_version": initial["project_version"], "answers": answers},
        )
        assert result.status_code == 422, result.text
    assert api.get(path).json()["version"] == initial["project_version"]
    assert (
        api.post(
            path + "/answers",
            json={"expected_version": 1, "answers": [{"question_id": "Q001", "value": "yes"}]},
        ).status_code
        == 409
    )
    llm.fail = True
    assert (
        api.post(
            path + "/answers",
            json={
                "expected_version": initial["project_version"],
                "answers": [{"question_id": "Q001", "value": "yes"}],
            },
        ).status_code
        == 503
    )
    assert api.get(path + "/analysis").json()["answers"] == {}
    llm.fail = False
    retry = api.post(
        path + "/answers",
        json={
            "expected_version": initial["project_version"],
            "answers": [{"question_id": "Q001", "value": "no"}],
        },
    )
    assert retry.status_code == 200


def test_no_clarifications_generates_draft(client, llm):
    api, _ = client
    llm.initial["questions"] = []
    llm.initial["gaps"] = []
    path = start(api)
    result = api.post(path + "/analyze", json={"expected_version": 2})
    assert result.status_code == 200, result.text
    assert result.json()["summary"]["status"] == "DRAFT"
    assert result.json()["state"] == "REQUIREMENTS_REVIEW"


def test_duplicate_ids_and_unknown_refs():
    data = document()
    data["requirements"].append(deepcopy(data["requirements"][0]))
    with pytest.raises(ValidationError):
        AnalysisDocument.model_validate(data)


@pytest.mark.parametrize(
    "value,valid", [(["A"], True), (["A", "A"], False), (["C"], False), ("A", False), ([], False)]
)
def test_multi_select_validation(value, valid):
    data = document()
    data["questions"] = [{**data["questions"][0], "type": "multi_select", "options": ["A", "B"]}]
    parsed = AnalysisDocument.model_validate(data)
    answer = [Answer(question_id="Q001", value=value)]
    if valid:
        validate_answers(parsed, {}, answer)
    else:
        with pytest.raises(ValueError):
            validate_answers(parsed, {}, answer)


def test_question_batch_limit_and_nonblocking_parent():
    data = document()
    data["questions"][0]["blocking"] = False
    parsed = AnalysisDocument.model_validate(data)
    assert required_questions(parsed, {}) == {"Q001"}
    assert not required_questions(parsed, {"Q001": "no"})
    assert required_questions(parsed, {"Q001": "yes"}) == {"Q002"}
    data["questions"] = [
        {**data["questions"][0], "id": f"Q{i:03}", "blocking": True} for i in range(1, 9)
    ]
    parsed = AnalysisDocument.model_validate(data)
    assert len(question_batch(parsed, {})) == 5


def test_unknown_model_source_is_rejected_atomically(client, llm):
    api, _ = client
    path = start(api)
    llm.initial["requirements"][0]["source_refs"] = ["invented-source"]
    response = api.post(path + "/analyze", json={"expected_version": 2})
    assert response.status_code == 502
    assert api.get(path).json()["state"] == "INTAKE"
    assert api.get(path).json()["version"] == 2
    assert api.get(path + "/analysis").status_code == 404


def test_invalid_targeted_patch_cannot_change_ids(client, llm, monkeypatch):
    api, _ = client
    path = start(api)
    initial = api.post(path + "/analyze", json={"expected_version": 2}).json()
    original_generate = llm.generate

    def invalid_patch(schema, instructions, payload):
        patch, usage = original_generate(schema, instructions, payload)
        patch.requirements[0].id = "R999"
        return patch, usage

    monkeypatch.setattr(llm, "generate", invalid_patch)
    response = api.post(
        path + "/answers",
        json={
            "expected_version": initial["project_version"],
            "answers": [{"question_id": "Q001", "value": "no"}],
        },
    )
    assert response.status_code == 502
    assert api.get(path + "/analysis").json()["answers"] == {}
    assert api.get(path + "/answers/history").json() == []


def test_commit_failure_rolls_back_graph_and_answers(client, llm, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    api, _ = client
    path = start(api)
    initial = api.post(path + "/analyze", json={"expected_version": 2}).json()
    original_commit = Session.commit

    def unavailable(self):
        raise SQLAlchemyError("sensitive database error")

    monkeypatch.setattr(Session, "commit", unavailable)
    response = api.post(
        path + "/answers",
        json={
            "expected_version": initial["project_version"],
            "answers": [{"question_id": "Q001", "value": "no"}],
        },
    )
    assert response.status_code == 503
    assert "sensitive" not in response.text
    monkeypatch.setattr(Session, "commit", original_commit)
    assert api.get(path + "/analysis").json()["answers"] == {}
    retry = api.post(
        path + "/answers",
        json={
            "expected_version": initial["project_version"],
            "answers": [{"question_id": "Q001", "value": "no"}],
        },
    )
    assert retry.status_code == 200


def test_initial_description_then_checklist_batch_then_complete_description(client, llm):
    api, _ = client
    llm.initial["requirements"][1]["source_refs"] = ["S1"]
    llm.initial["questions"][1]["condition"] = None
    path = start(api)
    initial = api.post(path + "/analyze", json={"expected_version": 2}).json()
    assert initial["initial_description"]["project_overview"] == "A customer portal."
    assert initial["initial_description"]["sections"]["Non-functional requirements"][0]["text"] == (
        "Security decision is undecided."
    )
    assert initial["summary"] is None
    result = api.post(
        path + "/answers",
        json={
            "expected_version": initial["project_version"],
            "answers": [
                {"question_id": "Q001", "value": "yes"},
                {"question_id": "Q002", "value": "TOTP"},
            ],
        },
    )
    assert result.status_code == 200, result.text
    final = result.json()
    assert len(llm.calls) == 2  # extraction + one update for the entire batch
    assert final["initial_description"] == initial["initial_description"]
    assert final["state"] == "REQUIREMENTS_REVIEW"
    assert len(final["summary"]["clarification_decisions"]) == 2
    requirement = final["document"]["requirements"][1]
    assert requirement["source_refs"] == ["S1", "answer:Q001:v1", "answer:Q002:v1"]
    assert requirement["origin"] == "customer_answer"
    assert "Customer clarification decisions" in final["markdown"]


def test_single_targeted_repair_recovers_bad_ids(client, llm, monkeypatch):
    api, _ = client
    path = start(api)
    initial = api.post(path + "/analyze", json={"expected_version": 2}).json()
    original = llm.generate
    calls = []

    def repairable(schema, instructions, payload):
        calls.append(deepcopy(payload))
        patch, usage = original(schema, instructions, payload)
        if len(calls) == 1:
            patch.requirements[0].id = "R999"
        return patch, usage

    monkeypatch.setattr(llm, "generate", repairable)
    response = api.post(
        path + "/answers",
        json={
            "expected_version": initial["project_version"],
            "answers": [{"question_id": "Q001", "value": "no"}],
        },
    )
    assert response.status_code == 200, response.text
    assert len(calls) == 2
    assert calls[1]["correction"]["expected_ids"] == ["R002"]
    assert response.json()["document"]["requirements"][1]["id"] == "R002"


def test_customer_can_resolve_an_assumption_without_model_citations(client, llm):
    api, _ = client
    llm.initial["requirements"][1]["category"] = "assumption"
    path = start(api)
    initial = api.post(path + "/analyze", json={"expected_version": 2}).json()
    result = api.post(
        path + "/answers",
        json={
            "expected_version": initial["project_version"],
            "answers": [{"question_id": "Q001", "value": "no"}],
        },
    )
    assert result.status_code == 200, result.text
    requirement = result.json()["document"]["requirements"][1]
    assert requirement["id"] == "R002"
    assert requirement["category"] == "non_functional"
    assert requirement["origin"] == "customer_answer"
    assert requirement["source_refs"] == ["answer:Q001:v1"]
