"""Business-content checks and explicit customer decisions; no approval authority."""

import re
from copy import deepcopy

from app.analysis_schemas import AnalysisDocument, GroundingReview
from app.services.llm import StructuredLLM
from app.services.ollama import LLMError
from app.services.validation import active, answered, required_questions

GROUNDING_PROMPT = """Independently review every extracted requirement against the provided sources.
Return one assessment per requirement ID. supported=true only when the source explicitly states
the capability or entails it without adding business decisions. Conventional features are not
automatically stated: 'manage products' does not establish CRUD operations, 'shopping cart'
does not establish quantity editing, and 'browse products' does not establish a product-detail
page. Mark elaborations, inferred implementation details, roles/permissions or decisions absent
from the source unsupported and explain why. Also classify each clarification's decision area
as a requirement category (e.g. privacy/performance/security are non_functional). Return every
question ID exactly once in question_categories. Do not answer questions or invent decisions."""


def review_grounding(llm: StructuredLLM, document: AnalysisDocument, sources: list[dict]):
    review, usage = llm.generate(
        GroundingReview,
        GROUNDING_PROMPT,
        {
            "sources": sources,
            "requirements": [r.model_dump() for r in document.requirements],
            "questions": [q.model_dump() for q in document.questions],
        },
    )
    ids = [a.requirement_id for a in review.assessments]
    if len(ids) != len(set(ids)) or set(ids) != {r.id for r in document.requirements}:
        raise LLMError("invalid_grounding_review", "Source review did not cover every requirement.")
    assessments = {a.requirement_id: a for a in review.assessments}
    qids = [q.question_id for q in review.question_categories]
    if len(qids) != len(set(qids)) or set(qids) != {q.id for q in document.questions}:
        raise LLMError(
            "invalid_grounding_review", "Source review omitted clarification categories."
        )
    categories = {q.question_id: q.category for q in review.question_categories}
    data = document.model_dump()
    for question in data["questions"]:
        question["decision_category"] = categories[question["id"]]
    for requirement in data["requirements"]:
        requirement["resolution"] = "ACTIVE"
        assessment = assessments[requirement["id"]]
        if not assessment.supported:
            requirement["origin"] = "assumption"
            data["grounding_notes"][requirement["id"]] = assessment.reason
    data["grounding_reviewed"] = True
    return AnalysisDocument.model_validate(data), usage


def normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def narrative(document: AnalysisDocument) -> str:
    """Build a business overview from grounded facts rather than meta-summary text."""
    goals = [
        r.text
        for r in document.requirements
        if r.category in {"business_goal", "scope"} and r.origin != "assumption"
    ]
    if not goals:
        goals = [r.text for r in document.requirements if r.origin != "assumption"][:3]
    if not goals:
        return "The project scope needs customer confirmation. Current proposals are listed below."
    unique = list(dict.fromkeys(goals))
    return "\n\n".join(unique)


def incorporate_decisions(
    document: AnalysisDocument, baseline: list[dict], answers: dict, refs: dict[str, str]
) -> AnalysisDocument:
    """Every active confirmed choice becomes a separate stable, verbatim business decision.

    This is deterministic rendering of customer input, not invented LLM reasoning.
    Existing generic requirements never serve as the sole evidence of incorporation.
    """
    data = deepcopy(document.model_dump())
    mapping = data["decision_requirement_ids"]
    if not mapping:
        occupied = {r["id"] for r in baseline}
        cursor = 1
        for question in document.questions:
            while f"R{cursor:03}" in occupied:
                cursor += 1
            mapping[question.id] = f"R{cursor:03}"
            occupied.add(mapping[question.id])
    generated_ids = set(mapping.values())
    data["requirements"] = [r for r in data["requirements"] if r["id"] not in generated_ids]
    for requirement in data["requirements"]:
        related = [q for q in document.questions if requirement["id"] in q.related_requirement_ids]
        if (
            requirement["origin"] == "assumption"
            and related
            and any(
                term in requirement["text"].casefold()
                for term in ("undecided", "not decided", "not been decided", "not specified")
            )
            and all(
                not active(q, document.questions, answers) or answered(q.id, answers)
                for q in related
            )
        ):
            requirement["resolution"] = "SUPERSEDED"
    for question in document.questions:
        if not active(question, document.questions, answers) or not answered(question.id, answers):
            continue
        value = answers[question.id]
        text = "; ".join(value) if isinstance(value, list) else value
        category = question.decision_category
        if any(g.kind == "security" and question.id in g.question_ids for g in document.gaps):
            category = "non_functional"
        if category == "assumption":
            category = "business_rule"
        data["requirements"].append(
            {
                "id": mapping[question.id],
                "category": category,
                "text": f"Customer decision — {question.text} Selected answer: {text}",
                "origin": "customer_answer",
                "source_refs": [refs[question.id]],
            }
        )
    data["decision_requirement_ids"] = mapping
    result = AnalysisDocument.model_validate(data)
    # Validate real answer content, not just labels or citations.
    by_id = {r.id: r for r in result.requirements}
    for q in result.questions:
        if active(q, result.questions, answers) and answered(q.id, answers):
            requirement = by_id.get(mapping[q.id])
            values = answers[q.id] if isinstance(answers[q.id], list) else [answers[q.id]]
            if not requirement or any(
                normalized(v) not in normalized(requirement.text) for v in values
            ):
                raise LLMError(
                    "missing_answer_content", "A customer decision is absent from the requirements."
                )
    return result


def gap_statuses(document: AnalysisDocument, answers: dict) -> list[dict]:
    rows = []
    for index, gap in enumerate(document.gaps, 1):
        ids = set(gap.question_ids)
        for q in document.questions:
            if q.condition and q.condition.question_id in ids:
                ids.add(q.id)
        questions = [q for q in document.questions if q.id in ids]
        applicable = [q for q in questions if active(q, document.questions, answers)]
        pending = [q.id for q in applicable if not answered(q.id, answers)]
        deferred = [qid for qid in pending if qid in answers]
        if not applicable:
            by_id = {q.id: q for q in document.questions}
            waiting = set()
            for q in questions:
                while q.condition:
                    q = by_id[q.condition.question_id]
                    if not answered(q.id, answers):
                        waiting.add(q.id)
            status = "UNANSWERED" if waiting else "NOT_APPLICABLE"
            pending = sorted(waiting)
        elif not pending:
            status = "RESOLVED"
        elif deferred:
            status = "DEFERRED"
        elif len(pending) != len(applicable):
            status = "PARTIAL"
        else:
            status = "UNANSWERED"
        rows.append(
            {
                "id": f"G{index:03}",
                **gap.model_dump(),
                "status": status,
                "pending_question_ids": pending,
            }
        )
    return rows


def completion(document: AnalysisDocument, answers: dict) -> dict:
    remaining = required_questions(document, answers)
    by_id = {q.id: q for q in document.questions}
    return {
        "total_questions": len(document.questions),
        "answered_questions": sum(
            active(q, document.questions, answers) and answered(q.id, answers)
            for q in document.questions
        ),
        "remaining_required_question_ids": sorted(remaining),
        "blocking_reasons": [f"{qid}: {by_id[qid].text}" for qid in sorted(remaining)],
        "summary_ready": not remaining,
    }
