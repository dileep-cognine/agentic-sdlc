"""Business-content checks and explicit customer decisions; no approval authority."""

import re
from copy import deepcopy

from app.analysis_schemas import AnalysisDocument, GroundingReview
from app.services.llm import StructuredLLM
from app.services.ollama import LLMError
from app.services.validation import active, answer_is_decided, answered, required_questions

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
    """Create atomic requirements only from accepted, evidence-checked interpretations."""
    data = deepcopy(document.model_dump())
    occupied = (
        {r["id"] for r in baseline}
        | set(data["decision_claim_ids"].values())
        | set(data["decision_requirement_ids"].values())
    )
    data["requirements"] = deepcopy(baseline)
    for requirement in data["requirements"]:
        related = [
            q
            for q in document.questions
            if requirement["id"] in q.related_requirement_ids and q.blocking
        ]
        if (
            requirement["origin"] == "assumption"
            and related
            and any(
                term in requirement["text"].casefold()
                for term in ("undecided", "not specified", "not decided", "not been decided")
            )
            and all(
                not active(q, document.questions, answers, document.answer_reviews)
                or answered(q.id, answers, document.answer_reviews)
                for q in related
            )
        ):
            requirement["resolution"] = "SUPERSEDED"
    cursor = 1
    for question in document.questions:
        if not active(
            question, document.questions, answers, document.answer_reviews
        ) or not answered(question.id, answers, document.answer_reviews):
            continue
        assessment = document.answer_reviews[question.id]
        for index, claim in enumerate(assessment.requirements):
            key = question.id + ":" + claim.key
            duplicate = next(
                (
                    r
                    for r in data["requirements"]
                    if normalized(r["text"]) == normalized(claim.text)
                    and r["category"] == claim.category
                ),
                None,
            )
            if duplicate:
                duplicate["origin"] = "customer_answer"
                duplicate["resolution"] = "ACTIVE"
                duplicate["source_refs"] = list(
                    dict.fromkeys([*duplicate["source_refs"], refs[question.id]])
                )
                data["decision_claim_ids"][key] = duplicate["id"]
                if index == 0:
                    data["decision_requirement_ids"][question.id] = duplicate["id"]
                continue
            rid = data["decision_claim_ids"].get(key)
            if rid and any(r["id"] == rid for r in data["requirements"]):
                rid = None
            if not rid:
                legacy = data["decision_requirement_ids"].get(question.id)
                if legacy and not any(
                    k.startswith(question.id + ":") for k in data["decision_claim_ids"]
                ):
                    rid = legacy
                else:
                    while f"R{cursor:03}" in occupied:
                        cursor += 1
                    rid = f"R{cursor:03}"
                occupied.add(rid)
                data["decision_claim_ids"][key] = rid
            if index == 0:
                data["decision_requirement_ids"][question.id] = rid
            data["requirements"].append(
                {
                    "id": rid,
                    "title": claim.title,
                    "text": claim.text,
                    "category": claim.category,
                    "origin": "customer_answer",
                    "source_refs": [refs[question.id]],
                }
            )
    return AnalysisDocument.model_validate(data)


def gap_statuses(document: AnalysisDocument, answers: dict) -> list[dict]:
    rows = []
    for index, gap in enumerate(document.gaps, 1):
        ids = set(gap.question_ids)
        for q in document.questions:
            if q.condition and q.blocking and q.condition.question_id in ids:
                ids.add(q.id)
        questions = [q for q in document.questions if q.id in ids]
        applicable = [
            q for q in questions if active(q, document.questions, answers, document.answer_reviews)
        ]
        pending = [q.id for q in applicable if not answered(q.id, answers, document.answer_reviews)]
        deferred = [qid for qid in pending if qid in answers]
        if not applicable:
            by_id = {q.id: q for q in document.questions}
            waiting = set()
            for q in questions:
                while q.condition:
                    q = by_id[q.condition.question_id]
                    if not answered(q.id, answers, document.answer_reviews):
                        waiting.add(q.id)
            status = "OPEN" if waiting else "RESOLVED"
            pending = sorted(waiting)
        elif not pending:
            status = "RESOLVED"
        elif any(
            qid in document.answer_reviews
            and document.answer_reviews[qid].status in {"UNCLEAR", "CONTRADICTORY", "NEEDS_REVIEW"}
            for qid in pending
        ):
            status = "ANSWER_NEEDS_CLARIFICATION"
        elif any(
            not answer_is_decided(answers[qid])
            or document.answer_reviews.get(qid)
            and document.answer_reviews[qid].reason.startswith("Draft saved")
            for qid in deferred
        ):
            status = "DEFERRED"
        elif deferred:
            status = "ANSWER_NEEDS_CLARIFICATION"
        else:
            status = "AWAITING_ANSWER"
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
            active(q, document.questions, answers, document.answer_reviews)
            and answered(q.id, answers, document.answer_reviews)
            for q in document.questions
        ),
        "remaining_required_question_ids": sorted(remaining),
        "blocking_reasons": [f"{qid}: {by_id[qid].text}" for qid in sorted(remaining)],
        "summary_ready": not remaining,
    }
