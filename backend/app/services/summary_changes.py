"""Customer summary change requests re-enter the persisted clarification loop."""

from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.analysis_schemas import AnalysisDocument, Question
from app.models import AnalysisVersion, GraphRuntime, Project, now
from app.services.analysis import (
    analysis_response,
    latest_analysis,
    record_checkpoint,
    reserve,
    runtime_state,
)
from app.services.summary_review import SummaryChanges, approval_for
from app.workflows.ba_graph import graph_definition
from app.workflows.checkpoints import TransactionalSaver
from app.workflows.state import WorkflowState, validate_transition


def request_summary_changes(db: Session, project: Project, data: SummaryChanges) -> dict:
    if approval_for(db, project.id):
        raise HTTPException(
            409, "Approved baselines are immutable; use a future change-control process"
        )
    previous = latest_analysis(db, project.id)
    if previous is None or previous.version != data.analysis_version:
        raise HTTPException(409, "Analysis version changed; refresh before requesting changes")
    state = deepcopy(runtime_state(db, project.id))
    doc = AnalysisDocument.model_validate(state["document"])
    ids = {r.id for r in doc.requirements}
    related = data.related_requirement_ids or [r["id"] for r in state["baseline"]]
    if len(related) > 100 or not set(related) <= ids:
        raise HTTPException(422, "Specify up to 100 existing related requirement IDs")
    if len(doc.questions) >= 50:
        raise HTTPException(409, "Question limit reached; refine an existing clarification")
    reserve(db, project, data.expected_version, {WorkflowState.REQUIREMENTS_REVIEW})
    record_checkpoint(db, project, previous.source_version, previous.version)
    qid = f"Q{max((int(q.id[1:]) for q in doc.questions), default=0) + 1:03}"
    question = Question(
        id=qid,
        text="Clarify the requested business changes: " + data.feedback,
        type="free_text",
        options=[],
        related_requirement_ids=related,
        blocking=True,
        priority=1,
        condition=None,
        why_it_matters="The customer requested changes to the requirement summary.",
    )
    doc.questions.append(question)
    raw = doc.model_dump()
    raw["gaps"].append(
        {
            "kind": "ambiguity",
            "description": data.feedback,
            "related_requirement_ids": related,
            "question_ids": [qid],
        }
    )
    doc = AnalysisDocument.model_validate(raw)
    saver = TransactionalSaver()
    graph = graph_definition(None, saver)  # this path only invokes deterministic update + interrupt
    graph.invoke(
        {
            **state,
            "document": doc.model_dump(),
            "submission": {
                "answers": state["answers"],
                "answer_refs": state["answer_refs"],
                "sources": state["sources"],
                "answer_reviews": doc.model_dump()["answer_reviews"],
                "usage": [],
            },
        },
        {"configurable": {"thread_id": project.id}},
    )
    updated = graph.get_state({"configurable": {"thread_id": project.id}}).values
    validate_transition(WorkflowState.ANALYZING, WorkflowState.AWAITING_CLARIFICATION)
    project.state = WorkflowState.AWAITING_CLARIFICATION
    project.version += 1
    project.updated_at = now()
    version = previous.version + 1
    db.add(
        AnalysisVersion(
            project_id=project.id,
            version=version,
            source_version=previous.source_version,
            document=updated["document"],
            answers=state["answers"],
            sources=state["sources"],
            summary=None,
            markdown=None,
            usage=state["usage"],
        )
    )
    db.get(GraphRuntime, project.id).payload = saver.export()
    record_checkpoint(db, project, previous.source_version, version)
    db.commit()
    return analysis_response(db, project)
