"""Executable analysis graph with durable human clarification interrupts."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.analysis_schemas import (
    AnalysisDocument,
    ClarificationDecision,
    DraftSummary,
)
from app.services.business_quality import (
    incorporate_decisions,
    narrative,
    review_grounding,
)
from app.services.llm import StructuredLLM
from app.services.ollama import LLMError
from app.services.validation import (
    active,
    answered,
    question_batch,
    required_questions,
    validate_sources,
)
from app.workflows.checkpoints import TransactionalSaver

EXTRACTION_PROMPT = """You are a business analyst. Extract every stated business goal, scope,
user role, functional requirement, non-functional requirement, business rule, constraint,
dependency and assumption. Use categories in the schema. Assign unique stable R001... IDs.
Preserve provided source IDs exactly. Label inferred assumptions explicitly. Never invent
business decisions. Identify missing requirements, ambiguity, conflicts, unclear business
rules, missing security decisions and missing functional behavior. Represent unresolved
decisions as gaps and prioritized questions (1 highest), with stable Q001... IDs.
Each gap needs a question and related requirement. If a missing area has no requirement,
create a clearly labelled assumption describing that it is undecided, never a proposed decision.
Include all necessary questions (maximum 50); avoid speculative boilerplate. The backend
batches them. Prefer practical checklist options using single_select, multi_select or yes_no.
Use free_text only when a useful honest option list cannot be provided. Options are proposed
choices for the customer, never assumed decisions. Questions can be single_select,
multi_select, yes_no (options yes,no), or free_text (empty options). Conditions refer only to
preceding questions. Use null when unconditional. Set blocking for decisions needed for a
reviewable requirement summary. Write overview as a business analyst narrative describing
the stated project purpose, users, key journeys and known scope. Keep it factual; do not state
unresolved decisions as facts. Output all schema fields, including empty lists."""
EXTRACTION_PROMPT += """ Do not expand a broad capability into assumed features: product management
does not establish CRUD, browsing does not establish detail pages, and carts do not establish
editing. Label such suggestions as assumptions. Set decision_category on each question.
Leave decision_requirement_ids and grounding_notes empty and grounding_reviewed false; these
are backend-owned. Never write placeholder introductions like 'high-level summary of source S1'."""


class GraphState(TypedDict, total=False):
    sources: list[dict]
    document: dict
    baseline: list[dict]
    answers: dict
    answer_refs: dict
    submission: dict | None
    summary: dict | None
    markdown: str | None
    usage: list[dict]


def summary_for(document: AnalysisDocument, answers: dict) -> tuple[dict, str]:
    headings = {
        "business_goal": "Business objectives",
        "scope": "Scope",
        "user_role": "User roles",
        "functional": "Functional requirements",
        "non_functional": "Non-functional requirements",
        "business_rule": "Business rules",
        "constraint": "Constraints",
        "dependency": "Dependencies",
        "assumption": "Assumptions",
    }
    summary = DraftSummary(
        project_overview=narrative(document),
        sections={
            heading: [
                r
                for r in document.requirements
                if r.resolution == "ACTIVE"
                and (
                    r.origin == "assumption"
                    if category == "assumption"
                    else r.category == category and r.origin != "assumption"
                )
            ]
            for category, heading in headings.items()
        },
        open_non_blocking_questions=[
            q
            for q in document.questions
            if not q.blocking
            and not answered(q.id, answers)
            and active(q, document.questions, answers)
        ],
        clarification_decisions=[
            ClarificationDecision(
                question_id=q.id,
                question=q.text,
                answer=answers[q.id],
                related_requirement_ids=q.related_requirement_ids,
                status="CONFIRMED" if answered(q.id, answers) else "DEFERRED",
                requirement_id=document.decision_requirement_ids.get(q.id),
            )
            for q in document.questions
            if q.id in answers and active(q, document.questions, answers)
        ],
    )
    lines = [
        "# Business analyst project description",
        "",
        "Status: DRAFT — pending customer review",
        "",
        "## Project overview",
        "",
        summary.project_overview,
    ]
    for heading, requirements in summary.sections.items():
        lines.extend(["", f"## {heading}", ""])
        lines.extend(
            f"- **{r.id}** [{r.origin}] {r.text} (sources: {', '.join(r.source_refs) or 'none'})"
            for r in requirements
        )
        if not requirements:
            lines.append("Not specified.")
    lines.extend(["", "## Customer clarification decisions", ""])
    for decision in summary.clarification_decisions:
        lines.append(
            f"- {decision.question_id} → {decision.requirement_id or 'unresolved'} "
            f"[{decision.status}]"
        )
    lines.extend(["", "## Open non-blocking questions", ""])
    lines.extend(f"- **{q.id}** {q.text}" for q in summary.open_non_blocking_questions)
    return summary.model_dump(mode="json"), "\n".join(lines)


def graph_definition(llm: StructuredLLM, saver: TransactionalSaver, batch_size: int = 5):
    def extract(state: GraphState) -> dict:
        llm.check()
        document, usage = llm.generate(
            AnalysisDocument, EXTRACTION_PROMPT, {"sources": state["sources"]}
        )
        try:
            validate_sources(document, state["sources"])
            if any(r.origin == "customer_answer" for r in document.requirements):
                raise ValueError("No answers exist at initial extraction")
        except ValueError:
            raise LLMError("invalid_output", "Extraction failed provenance validation.") from None
        data = document.model_dump()
        data.update(decision_requirement_ids={}, grounding_notes={}, grounding_reviewed=False)
        document, grounding_usage = review_grounding(
            llm, AnalysisDocument.model_validate(data), state["sources"]
        )
        return {
            "document": document.model_dump(mode="json"),
            "baseline": [r.model_dump() for r in document.requirements],
            "answers": {},
            "answer_refs": {},
            "usage": [usage.model_dump(), grounding_usage.model_dump()],
            "summary": None,
            "markdown": None,
        }

    def clarify(state: GraphState) -> dict:
        document = AnalysisDocument.model_validate(state["document"])
        submission = interrupt(
            {
                "questions": [
                    q.model_dump() for q in question_batch(document, state["answers"], batch_size)
                ]
            }
        )
        return {"submission": submission}

    def apply_answers(state: GraphState) -> dict:
        submission = state["submission"]
        document = AnalysisDocument.model_validate(state["document"])
        answers, refs = submission["answers"], submission["answer_refs"]
        sources = submission["sources"]
        # Customer choices are authoritative facts, not a request for invented rewrites.
        # Rebuild structured records only; no original document parsing or LLM call.
        updated = AnalysisDocument.model_validate(
            {**document.model_dump(), "requirements": state["baseline"]}
        )
        updated = incorporate_decisions(updated, state["baseline"], answers, refs)
        validate_sources(updated, sources)
        return {
            "document": updated.model_dump(mode="json"),
            "answers": answers,
            "answer_refs": refs,
            "sources": sources,
            "usage": state["usage"],
            "summary": None,
            "markdown": None,
            "submission": None,
        }

    def route(state: GraphState) -> str:
        document = AnalysisDocument.model_validate(state["document"])
        return (
            "clarify"
            if (not document.grounding_reviewed or required_questions(document, state["answers"]))
            else "summary"
        )

    def summarize(state: GraphState) -> dict:
        summary, markdown = summary_for(
            AnalysisDocument.model_validate(state["document"]), state["answers"]
        )
        return {"summary": summary, "markdown": markdown}

    graph = StateGraph(GraphState)
    graph.add_node("extract", extract)
    graph.add_node("clarify", clarify)
    graph.add_node("apply_answers", apply_answers)
    graph.add_node("summary", summarize)
    graph.add_conditional_edges(
        START, lambda s: "apply_answers" if s.get("submission") else "extract"
    )
    graph.add_conditional_edges("extract", route)
    graph.add_edge("clarify", "apply_answers")
    graph.add_conditional_edges("apply_answers", route)
    graph.add_edge("summary", END)
    return graph.compile(checkpointer=saver)
