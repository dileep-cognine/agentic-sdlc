from copy import deepcopy

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_analysis import FakeLLM, document, start

from app.analysis_schemas import AnalysisDocument, Answer, GroundingReview, Usage
from app.main import app
from app.models import AnalysisVersion
from app.services.answer_review import assess_answers
from app.services.business_quality import (
    completion,
    gap_statuses,
    incorporate_decisions,
    review_grounding,
)
from app.services.ollama import get_llm
from app.services.validation import question_batch
from app.workflows.ba_graph import summary_for


@pytest.fixture(name="llm")
def analysis_llm(client):
    fake = FakeLLM()
    app.dependency_overrides[get_llm] = lambda: fake
    return fake


def reviewed(doc, answers):
    reviews, _ = assess_answers(
        FakeLLM(), doc, [Answer(question_id=k, value=v) for k, v in answers.items()]
    )
    return AnalysisDocument.model_validate({**doc.model_dump(), "answer_reviews": reviews})


def shopping_document():
    return AnalysisDocument.model_validate(
        {
            "overview": "High-level summary of source S1.",
            "requirements": [
                {
                    "id": "R001",
                    "category": "business_goal",
                    "text": "Customers can place orders online.",
                    "origin": "stated",
                    "source_refs": ["S1"],
                },
                {
                    "id": "R002",
                    "category": "functional",
                    "text": "Admins can create, edit and delete products.",
                    "origin": "stated",
                    "source_refs": ["S1"],
                },
            ],
            "questions": [
                {
                    "id": "Q001",
                    "type": "single_select",
                    "text": "Which payment gateway is required?",
                    "options": ["Stripe", "PayPal"],
                    "related_requirement_ids": ["R001"],
                    "blocking": True,
                    "priority": 1,
                    "condition": None,
                    "decision_category": "dependency",
                },
                {
                    "id": "Q002",
                    "type": "multi_select",
                    "text": "Which delivery options are supported?",
                    "options": ["Standard delivery", "Store pickup", "Express delivery"],
                    "related_requirement_ids": ["R001"],
                    "blocking": True,
                    "priority": 2,
                    "condition": None,
                    "decision_category": "business_rule",
                },
            ],
            "gaps": [
                {
                    "kind": "missing",
                    "description": "Payment gateway is missing.",
                    "related_requirement_ids": ["R001"],
                    "question_ids": ["Q001"],
                },
                {
                    "kind": "missing",
                    "description": "Delivery options are missing.",
                    "related_requirement_ids": ["R001"],
                    "question_ids": ["Q002"],
                },
            ],
        }
    )


def test_selected_payment_and_delivery_are_real_requirements_not_just_citations():
    doc = shopping_document()
    baseline = [r.model_dump() for r in doc.requirements]
    answers = {"Q001": "Stripe", "Q002": ["Standard delivery", "Store pickup"]}
    doc = reviewed(doc, answers)
    result = incorporate_decisions(
        doc, baseline, answers, {"Q001": "answer:Q001:v1", "Q002": "answer:Q002:v1"}
    )
    by_id = {r.id: r for r in result.requirements}
    assert by_id["R001"].model_dump() == baseline[0]  # no false customer_answer label
    payment = by_id[result.decision_requirement_ids["Q001"]]
    delivery = by_id[result.decision_requirement_ids["Q002"]]
    assert "Stripe" in payment.text and payment.category == "dependency"
    delivery_text = " ".join(
        r.text for r in result.requirements if "answer:Q002:v1" in r.source_refs
    )
    assert "Standard delivery" in delivery_text and "Store pickup" in delivery_text
    assert "Express delivery" not in delivery.text
    assert payment.source_refs == ["answer:Q001:v1"]
    summary, markdown = summary_for(result, answers)
    assert "High-level summary" not in summary["project_overview"]
    assert "Stripe" in markdown and "Store pickup" in markdown
    assert all(g["status"] == "RESOLVED" for g in gap_statuses(result, answers))


def test_edit_removes_obsolete_choice_and_preserves_stable_decision_id():
    doc = shopping_document()
    baseline = [r.model_dump() for r in doc.requirements]
    doc = reviewed(doc, {"Q001": "Stripe"})
    original = incorporate_decisions(doc, baseline, {"Q001": "Stripe"}, {"Q001": "answer:Q001:v1"})
    original = reviewed(original, {"Q001": "PayPal"})
    edited = incorporate_decisions(
        original, baseline, {"Q001": "PayPal"}, {"Q001": "answer:Q001:v2"}
    )
    rid = original.decision_requirement_ids["Q001"]
    assert edited.decision_requirement_ids["Q001"] == rid
    requirement = next(r for r in edited.requirements if r.id == rid)
    assert "PayPal" in requirement.text and "Stripe" not in requirement.text
    assert requirement.source_refs == ["answer:Q001:v2"]
    assert len({r.id for r in edited.requirements}) == len(edited.requirements)


def test_unsupported_admin_crud_is_an_assumption_not_stated_scope():
    doc = shopping_document()

    class Reviewer:
        def generate(self, schema, instructions, payload):
            assert schema is GroundingReview
            assert payload["sources"][0]["text"] == "Admins can manage products."
            return GroundingReview(
                assessments=[
                    {
                        "requirement_id": "R001",
                        "supported": True,
                        "reason": "Orders are explicitly stated.",
                    },
                    {
                        "requirement_id": "R002",
                        "supported": False,
                        "reason": "Manage products does not establish CRUD permissions.",
                    },
                ],
                question_categories=[
                    {"question_id": "Q001", "category": "dependency"},
                    {"question_id": "Q002", "category": "business_rule"},
                ],
            ), Usage(input_tokens=1, output_tokens=1, latency_ms=1, attempts=1)

    reviewed, _ = review_grounding(
        Reviewer(), doc, [{"id": "S1", "location": "Brief", "text": "Admins can manage products."}]
    )
    summary, _ = summary_for(reviewed, {})
    assert summary["sections"]["Functional requirements"] == []
    assert summary["sections"]["Assumptions"][0]["id"] == "R002"
    assert reviewed.requirements[1].origin == "assumption"
    assert reviewed.grounding_notes["R002"]


def test_tbd_answer_does_not_resolve_blocking_gap():
    data = shopping_document().model_dump()
    data["questions"][0].update(type="free_text", options=[])
    doc = AnalysisDocument.model_validate(data)
    answers = {"Q001": "TBD"}
    assert "Q001" in completion(doc, answers)["remaining_required_question_ids"]
    assert gap_statuses(doc, answers)[0]["status"] == "DEFERRED"
    assert "Q001" in [q.id for q in question_batch(doc, answers)]
    folded = incorporate_decisions(
        doc, [r.model_dump() for r in doc.requirements], answers, {"Q001": "answer:Q001:v1"}
    )
    assert not any(r.origin == "customer_answer" for r in folded.requirements)


def test_conditional_followup_keeps_gap_partial_until_answered():
    doc = AnalysisDocument.model_validate(document())
    status = gap_statuses(reviewed(doc, {"Q001": "yes"}), {"Q001": "yes"})[0]
    assert status["status"] == "AWAITING_ANSWER"
    assert status["pending_question_ids"] == ["Q002"]
    assert (
        gap_statuses(
            reviewed(doc, {"Q001": "yes", "Q002": "TOTP"}), {"Q001": "yes", "Q002": "TOTP"}
        )[0]["status"]
        == "RESOLVED"
    )
    assert gap_statuses(reviewed(doc, {"Q001": "no"}), {"Q001": "no"})[0]["status"] == "RESOLVED"


def test_api_deferred_answer_is_saved_but_summary_is_blocked(client, llm):
    api, _ = client
    llm.initial["questions"][0].update(type="free_text", options=[])
    path = start(api)
    initial = api.post(path + "/analyze", json={"expected_version": 2}).json()
    result = api.post(
        path + "/answers",
        json={
            "expected_version": initial["project_version"],
            "answers": [{"question_id": "Q001", "value": "TBD"}],
        },
    ).json()
    assert result["answers"]["Q001"] == "TBD"
    assert result["state"] == "AWAITING_CLARIFICATION"
    assert result["summary"] is None
    assert result["gap_statuses"][0]["status"] == "DEFERRED"
    assert result["progress"]["remaining_required_question_ids"] == ["Q001"]


def test_reconcile_preserves_answers_and_old_versions(client, llm):
    api, engine = client
    path = start(api)
    initial = api.post(path + "/analyze", json={"expected_version": 2}).json()
    saved = api.post(
        path + "/answers",
        json={
            "expected_version": initial["project_version"],
            "answers": [{"question_id": "Q001", "value": "no"}],
        },
    ).json()
    with Session(engine) as db:
        row = db.scalar(select(AnalysisVersion).where(AnalysisVersion.version == 2))
        legacy = deepcopy(row.document)
        legacy["grounding_reviewed"] = False
        row.document = legacy
        db.commit()
    assert api.get(path + "/analysis").json()["needs_reconciliation"]
    repaired = api.post(path + "/reconcile", json={"expected_version": saved["project_version"]})
    assert repaired.status_code == 200, repaired.text
    result = repaired.json()
    assert not result["needs_reconciliation"]
    assert result["version"] == 3 and result["answers"] == saved["answers"]
    assert "shall support no" in result["markdown"]
    assert (
        result["document"]["decision_requirement_ids"]
        == saved["document"]["decision_requirement_ids"]
    )
    assert len(api.get(path + "/answers/history").json()) == 1
    assert not api.get(path + "/analysis?version=2").json()["document"]["grounding_reviewed"]
