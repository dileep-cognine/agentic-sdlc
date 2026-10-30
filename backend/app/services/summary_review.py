"""Human-controlled business baseline. No architecture execution or simulated approval."""

import hashlib
import json
from copy import deepcopy
from typing import Literal

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.analysis_schemas import AnalysisDocument, VersionRequest
from app.models import ArchitectureHandoff, Project, RequirementsApproval, SummaryRevision, now
from app.services.analysis import analysis_response, latest_analysis, record_checkpoint
from app.workflows.state import WorkflowState, validate_transition


class SummaryEdit(VersionRequest):
    analysis_version: int = Field(ge=1)
    overview: str = Field(min_length=1, max_length=5000)
    review_notes: str = Field(default="", max_length=5000)
    reviewer: str = Field(min_length=1, max_length=200)


class SummaryApprove(VersionRequest):
    analysis_version: int = Field(ge=1)
    summary_revision: int = Field(ge=0)
    reviewer: str = Field(min_length=1, max_length=200)
    confirm_business_understanding: Literal[True]


class SummaryChanges(VersionRequest):
    analysis_version: int = Field(ge=1)
    feedback: str = Field(min_length=1, max_length=1800)
    related_requirement_ids: list[str] = Field(default_factory=list, max_length=100)


def approval_for(db: Session, project_id: str):
    return db.scalar(
        select(RequirementsApproval)
        .where(RequirementsApproval.project_id == project_id)
        .order_by(RequirementsApproval.created_at.desc())
        .limit(1)
    )


def review_data(db: Session, project: Project) -> dict:
    row = latest_analysis(db, project.id)
    if row is None:
        raise HTTPException(404, "Analyze requirements before reviewing a summary")
    analysis = analysis_response(db, project)
    revision = db.scalar(
        select(SummaryRevision)
        .where(
            SummaryRevision.project_id == project.id,
            SummaryRevision.analysis_version == row.version,
        )
        .order_by(SummaryRevision.revision.desc())
        .limit(1)
    )
    approval = approval_for(db, project.id)
    handoff = db.scalar(
        select(ArchitectureHandoff).where(ArchitectureHandoff.project_id == project.id)
    )
    return {
        "analysis_version": row.version,
        "summary_revision": revision.revision if revision else 0,
        "status": "APPROVED" if approval else "DRAFT",
        "can_approve": project.state == WorkflowState.REQUIREMENTS_REVIEW
        and analysis["progress"]["summary_ready"],
        "blockers": analysis["progress"]["blocking_reasons"],
        "summary": approval.snapshot["summary"]
        if approval
        else revision.content
        if revision
        else row.summary,
        "markdown": approval.markdown
        if approval
        else revision.markdown
        if revision
        else row.markdown,
        "approval": {
            "reviewer": approval.reviewer,
            "analysis_version": approval.analysis_version,
            "summary_revision": approval.summary_revision,
            "content_hash": approval.content_hash,
            "created_at": approval.created_at,
        }
        if approval
        else None,
        "handoff": {
            "status": handoff.status,
            "message": (
                "Approved requirements saved for an Architecture Agent integration. "
                "No architecture has been generated."
            ),
        }
        if handoff
        else None,
        "revisions": [
            {"revision": r.revision, "reviewer": r.reviewer, "created_at": r.created_at}
            for r in db.scalars(
                select(SummaryRevision)
                .where(
                    SummaryRevision.project_id == project.id,
                    SummaryRevision.analysis_version == row.version,
                )
                .order_by(SummaryRevision.revision.desc())
            )
        ],
    }


def lock_review(db: Session, project: Project, expected: int, analysis_version: int) -> dict:
    if project.state != WorkflowState.REQUIREMENTS_REVIEW or approval_for(db, project.id):
        raise HTTPException(
            409, "Only an unapproved requirement summary can be changed or approved"
        )
    data = analysis_response(db, project)
    if data["version"] != analysis_version:
        raise HTTPException(409, "Analysis version changed; review the current version")
    if not data["progress"]["summary_ready"] or not data["summary"]:
        raise HTTPException(409, "Resolve blocking decisions and source review before approval")
    result = db.execute(
        update(Project)
        .where(
            Project.id == project.id,
            Project.version == expected,
            Project.state == WorkflowState.REQUIREMENTS_REVIEW,
        )
        .values(version=Project.version + 1, updated_at=now())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "Project version changed; refresh before continuing")
    db.refresh(project)
    return data


def edit_summary(db: Session, project: Project, data: SummaryEdit) -> dict:
    analysis = lock_review(db, project, data.expected_version, data.analysis_version)
    summary = deepcopy(analysis["summary"])
    original = latest_analysis(db, project.id)
    original_overview = original.summary["project_overview"]
    summary["project_overview"] = data.overview
    summary["review_notes"] = data.review_notes
    markdown = original.markdown.replace(original_overview, data.overview, 1)
    if data.review_notes:
        markdown += "\n\n## Reviewer notes\n\n" + data.review_notes
    revision = (
        db.scalar(
            select(func.max(SummaryRevision.revision)).where(
                SummaryRevision.project_id == project.id,
                SummaryRevision.analysis_version == data.analysis_version,
            )
        )
        or 0
    ) + 1
    db.add(
        SummaryRevision(
            project_id=project.id,
            analysis_version=data.analysis_version,
            revision=revision,
            content=summary,
            markdown=markdown,
            reviewer=data.reviewer,
        )
    )
    record_checkpoint(db, project, analysis["source_version"], data.analysis_version)
    db.commit()
    return review_data(db, project)


def approve_summary(db: Session, project: Project, data: SummaryApprove) -> dict:
    analysis = lock_review(db, project, data.expected_version, data.analysis_version)
    current = review_data(db, project)
    if current["summary_revision"] != data.summary_revision:
        raise HTTPException(409, "Summary revision changed; review the latest draft")
    summary = deepcopy(current["summary"])
    summary["status"] = "APPROVED"
    snapshot = {
        "project_id": project.id,
        "analysis_version": data.analysis_version,
        "summary_revision": data.summary_revision,
        "summary": summary,
        "requirements": AnalysisDocument.model_validate(analysis["document"]).model_dump(),
        "answers": analysis["answers"],
        "scope": "BUSINESS_REQUIREMENTS_ONLY",
    }
    digest = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    markdown = current["markdown"].replace(
        "Status: DRAFT — pending customer review",
        "Status: APPROVED — business understanding baseline",
        1,
    )
    markdown += (
        "\n\nApproval confirms business understanding. "
        "Technical design is not approved by this action."
    )
    approval = RequirementsApproval(
        project_id=project.id,
        analysis_version=data.analysis_version,
        summary_revision=data.summary_revision,
        reviewer=data.reviewer,
        content_hash=digest,
        snapshot=snapshot,
        markdown=markdown,
    )
    db.add(approval)
    db.flush()
    db.add(
        ArchitectureHandoff(
            project_id=project.id,
            approval_id=approval.id,
            payload={
                "schema_version": 1,
                "approval_id": approval.id,
                "content_hash": digest,
                **snapshot,
            },
        )
    )
    validate_transition(
        WorkflowState.REQUIREMENTS_REVIEW, WorkflowState.AWAITING_ARCHITECTURE, human_approved=True
    )
    project.state = WorkflowState.AWAITING_ARCHITECTURE
    record_checkpoint(db, project, analysis["source_version"], data.analysis_version)
    db.commit()
    return review_data(db, project)
