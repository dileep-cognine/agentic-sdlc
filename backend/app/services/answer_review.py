"""Question-specific semantic checks and grounded, atomic interpretations."""

from app.analysis_schemas import (
    AnalysisDocument,
    Answer,
    AnswerAssessment,
    AnswerReviewBatch,
    Question,
)
from app.services.llm import StructuredLLM
from app.services.ollama import LLMError
from app.services.validation import answer_is_decided

PROMPT = """Evaluate each answer against its question and context, not mere length.
Use VALID only for a meaningful, sufficiently specified decision. Random strings such as fgh,
dfgh, dsfgh, sdfghj or dasfghj are UNCLEAR, not authentication/payment/inventory/shipping policies.
Not decided yet is INCOMPLETE and produces no requirements. Missing detail is INCOMPLETE,
ambiguous wording UNCLEAR, conflicting instructions CONTRADICTORY, uncertainty NEEDS_REVIEW.
An unusual but clear choice can be VALID; do not reject it because it is unfamiliar or unwise.
Return a concise reason and suggested clarification. Interpret accepted answers into atomic
business requirements, not 'Customer decision ... selected answer' or a copy of the question.
Use stable semantic keys such as customer_authentication or admin_authentication across edits.
Each requirement needs an EXACT source_excerpt from the answer or explicit confirmation reason.
Do not invent providers, targets, compliance obligations or implementation details. For example,
email/password for customers and SSO for admins yields TWO requirements. An unspecified SSO
provider remains an open_detail, not an invented provider. open_details must be relevant and
not repeat existing questions. For uncertain answers you may propose clearly grounded clauses
for explicit human confirmation, but return no clauses for gibberish or contradictory answers.
confirmed_by_customer is always false in your response; only the backend may grant confirmation.
Never approve a project or change workflow state. Return exactly one result per submitted ID."""


def assess_answers(
    llm: StructuredLLM, document: AnalysisDocument, submitted: list[Answer], draft: bool = False
) -> tuple[dict, list[dict]]:
    if draft:
        return {
            a.question_id: AnswerAssessment(
                question_id=a.question_id,
                status="INCOMPLETE",
                reason="Draft saved; not submitted for validation.",
                suggested_clarification="Submit when ready.",
                requirements=[],
                open_details=[],
            ).model_dump()
            for a in submitted
        }, []
    by_id = {q.id: q for q in document.questions}
    result, usage = llm.generate(
        AnswerReviewBatch,
        PROMPT,
        {
            "answers": [
                {
                    "question": by_id[a.question_id].model_dump(),
                    "answer": a.value,
                    "confirmation_reason": a.confirmation_reason if a.confirm else "",
                }
                for a in submitted
            ],
            "existing_questions": [{"id": q.id, "text": q.text} for q in document.questions],
            "existing_requirement_keys": list(document.decision_claim_ids),
        },
    )
    ids = [r.question_id for r in result.assessments]
    if len(ids) != len(set(ids)) or set(ids) != {a.question_id for a in submitted}:
        raise LLMError(
            "invalid_answer_review", "The answer review did not cover the submitted questions."
        )
    answers = {a.question_id: a for a in submitted}
    reviews = {}
    for assessment in result.assessments:
        answer = answers[assessment.question_id]
        evidence = "\n".join(answer.value) if isinstance(answer.value, list) else answer.value
        if answer.confirm:
            evidence += "\n" + answer.confirmation_reason
        keys = [r.key for r in assessment.requirements]
        if len(keys) != len(set(keys)) or any(
            r.source_excerpt not in evidence for r in assessment.requirements
        ):
            raise LLMError(
                "invalid_answer_review", "The interpretation lacks valid answer evidence."
            )
        assessment.confirmed_by_customer = False
        assessment.confirmation_requested = answer.confirm
        assessment.confirmation_reason = answer.confirmation_reason if answer.confirm else ""
        if (
            answer.confirm
            and assessment.status in {"NEEDS_REVIEW", "INCOMPLETE"}
            and assessment.requirements
            and answer_is_decided(answer.value)
        ):
            assessment.confirmed_by_customer = True
            assessment.confirmation_reason = answer.confirmation_reason
        if assessment.status == "VALID" and not assessment.requirements:
            raise LLMError(
                "invalid_answer_review", "A valid answer needs a grounded interpretation."
            )
        if assessment.status in {"UNCLEAR", "CONTRADICTORY"}:
            assessment.requirements = []
        if any(
            "selected answer:" in r.text.casefold()
            or r.text.casefold().startswith("customer decision")
            for r in assessment.requirements
        ):
            raise LLMError(
                "invalid_answer_review",
                "The interpretation must contain atomic requirements, not a repeated Q&A.",
            )
        reviews[assessment.question_id] = assessment.model_dump()
    return reviews, [{**usage.model_dump(), "operation": "answer_review"}]


def add_followups(document: AnalysisDocument, answers: dict) -> AnalysisDocument:
    data = document.model_dump()
    seen = {q.text.casefold().strip(): q.id for q in document.questions}
    next_id = max((int(q.id[1:]) for q in document.questions), default=0) + 1
    for qid, assessment in document.answer_reviews.items():
        if assessment.status != "VALID" and not assessment.confirmed_by_customer:
            continue
        parent = next(q for q in document.questions if q.id == qid)
        for text in assessment.open_details:
            normalized = text.casefold().strip()
            if normalized in seen:
                for q in data["questions"]:
                    if q["id"] == seen[normalized] and q["generated_from_question_id"] == qid:
                        q["condition"]["any_of"] = (
                            answers[qid] if isinstance(answers[qid], list) else [answers[qid]]
                        )
                continue
            if len(data["questions"]) >= 50:
                raise LLMError("question_limit", "Too many open details; refine this answer.")
            child = Question(
                id=f"Q{next_id:03}",
                text=text,
                type="free_text",
                options=[],
                related_requirement_ids=parent.related_requirement_ids,
                blocking=False,
                priority=3,
                decision_category=parent.decision_category,
                generated_from_question_id=qid,
                condition={
                    "question_id": qid,
                    "any_of": answers[qid] if isinstance(answers[qid], list) else [answers[qid]],
                },
            )
            data["questions"].append(child.model_dump())
            data["gaps"].append(
                {
                    "kind": "missing",
                    "description": text,
                    "related_requirement_ids": parent.related_requirement_ids,
                    "question_ids": [child.id],
                }
            )
            seen[normalized] = child.id
            next_id += 1
    return AnalysisDocument.model_validate(data)
