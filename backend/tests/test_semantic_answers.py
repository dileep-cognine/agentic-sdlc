import pytest
from test_analysis import FakeLLM, start

from app.analysis_schemas import AnswerReviewBatch, Usage
from app.main import app
from app.services.ollama import get_llm


@pytest.fixture
def setup(client):
    api, engine = client
    model = FakeLLM()
    model.initial["questions"] = [model.initial["questions"][0]]
    model.initial["questions"][0].update(
        type="free_text", options=[], text="How should authentication work?"
    )
    app.dependency_overrides[get_llm] = lambda: model
    path = start(api)
    initial = api.post(path + "/analyze", json={"expected_version": 2}).json()
    return api, model, path, initial


def save(api, path, initial, value, **extra):
    return api.post(
        path + "/answers",
        json={
            "expected_version": initial["project_version"],
            "answers": [
                {
                    "question_id": "Q001",
                    "value": value,
                    "question_version": initial["version"],
                    **extra,
                }
            ],
        },
    )


@pytest.mark.parametrize("junk", ["fgh", "dfgh", "dsfgh", "sdfghj", "dasfghj"])
def test_meaningless_answers_remain_unresolved_and_never_create_rules(setup, junk):
    api, model, path, initial = setup
    result = save(api, path, initial, junk)
    assert result.status_code == 200
    data = result.json()
    assert data["answer_feedback"]["Q001"]["status"] == "UNCLEAR"
    assert data["answers"]["Q001"] == junk
    assert data["gap_statuses"][0]["status"] == "ANSWER_NEEDS_CLARIFICATION"
    assert data["state"] == "AWAITING_CLARIFICATION" and data["summary"] is None
    assert not any(
        r["classification"] == "CUSTOMER_CONFIRMED" for r in data["document"]["requirements"]
    )
    assert api.get(path + "/validations").json()[0]["assessment"]["status"] == "UNCLEAR"
    assert api.post(path + "/approve", json={}).status_code in (404, 405)


def install_review(model, status="VALID", details=None):
    original = model.generate

    def generate(schema, instructions, payload):
        if schema is not AnswerReviewBatch:
            return original(schema, instructions, payload)
        claims = [
            {
                "key": "customer_auth",
                "title": "Customer authentication",
                "text": "Customers shall authenticate using email and password.",
                "category": "functional",
                "source_excerpt": "email/password",
            },
            {
                "key": "admin_auth",
                "title": "Administrator authentication",
                "text": "Administrators shall authenticate through SSO.",
                "category": "functional",
                "source_excerpt": "SSO",
            },
        ]
        return schema.model_validate(
            {
                "assessments": [
                    {
                        "question_id": "Q001",
                        "status": status,
                        "reason": "The business intent is clear."
                        if status == "VALID"
                        else "Please confirm the unusual decision.",
                        "suggested_clarification": "Confirm or explain the intended access policy.",
                        "requirements": claims,
                        "open_details": details or [],
                    }
                ]
            }
        ), Usage(input_tokens=20, output_tokens=30, latency_ms=2, attempts=1)

    model.generate = generate


def test_valid_authentication_becomes_atomic_requirements_and_relevant_followup(setup):
    api, model, path, initial = setup
    install_review(model, details=["Which SSO provider should administrators use?"])
    result = save(api, path, initial, "Customers use email/password; admins use SSO").json()
    requirements = [
        r for r in result["document"]["requirements"] if r["classification"] == "CUSTOMER_CONFIRMED"
    ]
    assert len(requirements) == 2
    assert {r["text"] for r in requirements} == {
        "Customers shall authenticate using email and password.",
        "Administrators shall authenticate through SSO.",
    }
    assert all(r["source_refs"] == ["answer:Q001:v1"] for r in requirements)
    assert all("Selected answer" not in r["text"] for r in requirements)
    assert result["summary"]["status"] == "DRAFT"
    assert len(result["questions"]) == 1 and "SSO provider" in result["questions"][0]["text"]
    assert not result["questions"][0]["blocking"]
    assert "Azure" not in result["markdown"]
    assert api.get(path + "/answers/history").json()[0]["revision"] == 1


def test_uncertain_answer_requires_review_and_can_be_explicitly_confirmed_with_audit(setup):
    api, model, path, initial = setup
    install_review(model, status="NEEDS_REVIEW")
    text = "Customers use email/password; admins use SSO"
    first = save(api, path, initial, text).json()
    assert first["summary"] is None
    assert not first["answer_feedback"]["Q001"]["confirmed_by_customer"]
    confirmed = save(
        api,
        path,
        first,
        text,
        confirm=True,
        confirmation_reason="I confirm that these authentication methods are intentional.",
    ).json()
    assert confirmed["progress"]["summary_ready"]
    review = confirmed["answer_feedback"]["Q001"]
    assert review["status"] == "NEEDS_REVIEW" and review["confirmed_by_customer"]
    assert review["confirmation_reason"]
    assert len(api.get(path + "/validations").json()) == 2


def test_edit_invalidates_old_requirements_and_reopens_gap(setup):
    api, model, path, initial = setup
    first = save(api, path, initial, "Email and password").json()
    assert first["progress"]["summary_ready"]
    old_ids = set(first["document"]["decision_claim_ids"].values())
    edited = save(api, path, first, "fgh").json()
    assert edited["state"] == "AWAITING_CLARIFICATION"
    assert edited["summary"] is None
    assert not old_ids.intersection(r["id"] for r in edited["document"]["requirements"])
    again = save(api, path, edited, "Email and password").json()
    assert set(again["document"]["decision_claim_ids"].values()) == old_ids


def test_stale_question_duplicate_submission_and_draft_policy(setup):
    api, model, path, initial = setup
    response = api.post(
        path + "/answers",
        json={
            "expected_version": initial["project_version"],
            "answers": [
                {"question_id": "Q001", "value": "Email password", "question_version": 999}
            ],
        },
    )
    assert response.status_code == 409
    calls = len(model.calls)
    draft = api.post(
        path + "/answers",
        json={
            "expected_version": initial["project_version"],
            "draft": True,
            "answers": [{"question_id": "Q001", "value": "Still writing"}],
        },
    ).json()
    assert len(model.calls) == calls and not draft["progress"]["summary_ready"]
    valid = save(api, path, draft, "Email password").json()
    assert save(api, path, valid, "Email password").status_code == 409


def test_unclear_answer_cannot_be_confirmed_past_validation(setup):
    api, model, path, initial = setup
    data = save(
        api, path, initial, "fgh", confirm=True, confirmation_reason="I am trying to confirm this."
    ).json()
    assert not data["answer_feedback"]["Q001"]["confirmed_by_customer"]
    assert data["answer_feedback"]["Q001"]["confirmation_requested"]
    assert not data["progress"]["summary_ready"]


def test_not_decided_is_persisted_as_deferred_not_fabricated(setup):
    api, model, path, initial = setup
    result = save(api, path, initial, "Not decided yet").json()
    assert result["gap_statuses"][0]["status"] == "DEFERRED"
    assert result["answer_feedback"]["Q001"]["requirements"] == []
    assert result["summary"] is None


def test_relevant_followup_is_not_duplicated_after_edit(setup):
    api, model, path, initial = setup
    install_review(model, details=["Which SSO provider should administrators use?"])
    first = save(api, path, initial, "Customers use email/password; admins use SSO").json()
    second = save(api, path, first, "Customers use email/password; admins use SSO.").json()
    questions = [
        q for q in second["document"]["questions"] if q["generated_from_question_id"] == "Q001"
    ]
    assert len(questions) == 1 and questions[0]["id"] == first["questions"][0]["id"]


def test_contradictory_semantic_review_cannot_resolve_gap(setup):
    api, model, path, initial = setup
    install_review(model, status="CONTRADICTORY")
    result = save(api, path, initial, "Require email/password and SSO but prohibit SSO").json()
    assert result["answer_feedback"]["Q001"]["status"] == "CONTRADICTORY"
    assert result["answer_feedback"]["Q001"]["requirements"] == []
    assert not result["progress"]["summary_ready"]


def test_clear_unusual_decision_is_not_rejected_by_a_product_allowlist(setup):
    api, model, path, initial = setup
    result = save(
        api, path, initial, "Use printed one-time access vouchers issued by support staff"
    ).json()
    assert result["answer_feedback"]["Q001"]["status"] == "VALID"
    assert result["progress"]["summary_ready"]


def test_conflicting_multi_select_choices_are_rejected_deterministically():
    from test_analysis import document

    from app.analysis_schemas import AnalysisDocument, Answer
    from app.services.validation import validate_answers

    data = document()
    data["questions"] = [
        {
            **data["questions"][0],
            "type": "multi_select",
            "options": ["Password only", "SSO only", "None"],
            "exclusive_options": ["None"],
            "conflicting_options": [["Password only", "SSO only"]],
        }
    ]
    parsed = AnalysisDocument.model_validate(data)
    for value in [["None", "SSO only"], ["Password only", "SSO only"]]:
        with pytest.raises(ValueError):
            validate_answers(parsed, {}, [Answer(question_id="Q001", value=value)])


@pytest.mark.parametrize("value", [False, 123, {}, ["Email"]])
def test_unsupported_free_text_answer_types_are_rejected_before_model_calls(setup, value):
    api, model, path, initial = setup
    before = len(model.calls)
    assert save(api, path, initial, value).status_code == 422
    assert len(model.calls) == before
