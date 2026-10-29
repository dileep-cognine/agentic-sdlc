"""Application-owned workflow transitions, CAS locking and atomic version persistence."""

from copy import deepcopy

from fastapi import HTTPException
from langgraph.types import Command
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.analysis_schemas import AnalysisDocument, AnswerSubmission
from app.config import get_settings
from app.models import (
    AnalysisVersion,
    ClarificationAnswer,
    GraphRuntime,
    Project,
    RequirementVersion,
    WorkflowCheckpoint,
    now,
)
from app.services.document_parser import text_sources
from app.services.llm import StructuredLLM
from app.services.validation import (
    active,
    invalidate_descendants,
    question_batch,
    required_questions,
    validate_answers,
)
from app.workflows.ba_graph import graph_definition, summary_for
from app.workflows.checkpoints import TransactionalSaver
from app.workflows.state import WorkflowState, validate_transition


def latest_analysis(db: Session, project_id: str) -> AnalysisVersion | None:
    return db.scalar(
        select(AnalysisVersion)
        .where(AnalysisVersion.project_id == project_id)
        .order_by(AnalysisVersion.version.desc())
        .limit(1)
    )


def runtime_state(db: Session, project_id: str) -> dict:
    runtime = db.get(GraphRuntime, project_id)
    if runtime is None:
        raise HTTPException(409, "No persisted analysis checkpoint")
    saved = TransactionalSaver(deepcopy(runtime.payload)).get_tuple(
        {"configurable": {"thread_id": project_id}}
    )
    if saved is None:
        raise HTTPException(409, "No persisted analysis checkpoint")
    return saved.checkpoint["channel_values"]


def record_checkpoint(
    db: Session, project: Project, source_version: int, analysis_version: int | None
) -> None:
    db.add(
        WorkflowCheckpoint(
            project_id=project.id,
            project_version=project.version,
            state=project.state,
            payload={
                "project_id": project.id,
                "project_version": project.version,
                "state": project.state,
                "requirement_version": source_version,
                "analysis_version": analysis_version,
            },
        )
    )


def reserve(db: Session, project: Project, expected: int, allowed: set[str]) -> None:
    if project.state not in allowed:
        raise HTTPException(409, "Operation is not permitted in the current workflow state")
    validate_transition(WorkflowState(project.state), WorkflowState.ANALYZING)
    result = db.execute(
        update(Project)
        .where(
            Project.id == project.id,
            Project.version == expected,
            Project.state.in_(allowed),
        )
        .values(version=Project.version + 1, state=WorkflowState.ANALYZING, updated_at=now())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Project version changed; refresh before retrying")
    db.refresh(project)


def run_analysis(
    db: Session,
    project: Project,
    expected: int,
    llm: StructuredLLM,
    submission: AnswerSubmission | None = None,
) -> dict:
    """A request owns a project CAS lock until graph+domain commit; failures roll back.

    LLM calls are synchronous in a FastAPI worker thread. No partially completed
    answer or graph checkpoint is committed on failure or worker interruption.
    """
    allowed = (
        {WorkflowState.INTAKE}
        if submission is None
        else {WorkflowState.AWAITING_CLARIFICATION, WorkflowState.REQUIREMENTS_REVIEW}
    )
    reserve(db, project, expected, allowed)
    source = db.scalar(
        select(RequirementVersion)
        .where(RequirementVersion.project_id == project.id)
        .order_by(RequirementVersion.version.desc())
        .limit(1)
    )
    if source is None:
        raise HTTPException(409, "Submit requirements before analyzing")
    previous = latest_analysis(db, project.id)
    analysis_version = previous.version + 1 if previous else 1
    record_checkpoint(db, project, source.version, previous.version if previous else None)
    runtime = db.get(GraphRuntime, project.id)
    saver = TransactionalSaver(deepcopy(runtime.payload) if runtime else None)
    graph = graph_definition(llm, saver, get_settings().clarification_batch_size)
    config = {"configurable": {"thread_id": project.id}, "recursion_limit": 30}
    if submission is None:
        graph_input = {
            "sources": source.source_data or text_sources(source.text),
            "submission": None,
        }
    else:
        state = graph.get_state(config).values
        document = AnalysisDocument.model_validate(state["document"])
        try:
            validate_answers(document, state["answers"], submission.answers)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        # Only presented pending questions or previously answered questions can be changed.
        visible = {
            q.id
            for q in question_batch(
                document, state["answers"], get_settings().clarification_batch_size
            )
        }
        if any(a.question_id not in visible | set(state["answers"]) for a in submission.answers):
            raise HTTPException(422, "Answer questions from the current batch")
        changed = {a.question_id for a in submission.answers}
        invalidated = invalidate_descendants(document, state["answers"], set(changed))
        if invalidated & changed:
            raise HTTPException(
                422, "Save a changed parent before answering its dependent questions"
            )
        effective = {k: v for k, v in state["answers"].items() if k not in invalidated}
        refs = {k: v for k, v in state["answer_refs"].items() if k not in invalidated}
        old_refs = {
            state["answer_refs"][k] for k in changed | invalidated if k in state["answer_refs"]
        }
        sources = [s for s in state["sources"] if s["id"] not in old_refs]
        for answer in submission.answers:
            revision = (
                db.scalar(
                    select(func.max(ClarificationAnswer.revision)).where(
                        ClarificationAnswer.project_id == project.id,
                        ClarificationAnswer.question_id == answer.question_id,
                    )
                )
                or 0
            ) + 1
            effective[answer.question_id] = answer.value
            ref = f"answer:{answer.question_id}:v{revision}"
            refs[answer.question_id] = ref
            sources.append(
                {
                    "id": ref,
                    "location": f"Customer answer {answer.question_id} v{revision}",
                    "text": ", ".join(answer.value)
                    if isinstance(answer.value, list)
                    else answer.value,
                }
            )
            db.add(
                ClarificationAnswer(
                    project_id=project.id,
                    question_id=answer.question_id,
                    revision=revision,
                    analysis_version=analysis_version,
                    value=answer.value,
                )
            )
        affected = {
            r
            for q in document.questions
            if q.id in changed | invalidated
            for r in q.related_requirement_ids
        }
        answer_input = {
            "affected": sorted(affected),
            "answers": effective,
            "answer_refs": refs,
            "sources": sources,
        }
        if graph.get_state(config).next:
            graph_input = Command(resume=answer_input)
        else:
            graph_input = {"submission": answer_input}
    graph.invoke(graph_input, config)
    state = graph.get_state(config).values
    document = AnalysisDocument.model_validate(state["document"])
    target = (
        WorkflowState.AWAITING_CLARIFICATION
        if required_questions(document, state["answers"])
        else WorkflowState.REQUIREMENTS_REVIEW
    )
    validate_transition(WorkflowState.ANALYZING, target)
    project.state = target
    project.version += 1
    project.updated_at = now()
    db.add(
        AnalysisVersion(
            project_id=project.id,
            version=analysis_version,
            source_version=source.version,
            document=state["document"],
            answers=state["answers"],
            sources=state["sources"],
            summary=state.get("summary"),
            markdown=state.get("markdown"),
            usage=state["usage"],
        )
    )
    if runtime:
        runtime.payload = saver.export()
    else:
        db.add(GraphRuntime(project_id=project.id, payload=saver.export()))
    record_checkpoint(db, project, source.version, analysis_version)
    db.commit()
    return analysis_response(db, project)


def analysis_response(db: Session, project: Project, version: int | None = None) -> dict:
    row = (
        latest_analysis(db, project.id)
        if version is None
        else db.scalar(
            select(AnalysisVersion).where(
                AnalysisVersion.project_id == project.id, AnalysisVersion.version == version
            )
        )
    )
    if row is None:
        raise HTTPException(404, "Analysis not found")
    state = runtime_state(db, project.id)
    document = AnalysisDocument.model_validate(row.document)
    initial = db.scalar(
        select(AnalysisVersion).where(
            AnalysisVersion.project_id == project.id, AnalysisVersion.version == 1
        )
    )
    initial_description, _ = summary_for(AnalysisDocument.model_validate(initial.document), {})
    return {
        "project_id": project.id,
        "project_version": project.version,
        "state": project.state
        if version is None
        else (
            WorkflowState.REQUIREMENTS_REVIEW
            if row.summary
            else WorkflowState.AWAITING_CLARIFICATION
        ),
        "version": row.version,
        "source_version": row.source_version,
        "document": row.document,
        "initial_description": initial_description,
        "sources": row.sources,
        "summary": row.summary,
        "markdown": row.markdown,
        "usage": row.usage,
        "answers": row.answers,
        "questions": [
            q.model_dump()
            for q in question_batch(
                document, state["answers"], get_settings().clarification_batch_size
            )
        ]
        if version is None
        else [],
        "answered_questions": [
            q.model_dump()
            for q in document.questions
            if q.id in state["answers"] and active(q, document.questions, state["answers"])
        ]
        if version is None
        else [],
    }
