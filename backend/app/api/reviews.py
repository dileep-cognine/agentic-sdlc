from uuid import UUID

from fastapi import APIRouter

from app.api.projects import Database, get_project
from app.services.summary_changes import request_summary_changes
from app.services.summary_review import (
    SummaryApprove,
    SummaryChanges,
    SummaryEdit,
    approve_summary,
    edit_summary,
    review_data,
)

router = APIRouter()


@router.get("/projects/{project_id}/summary-review")
def review(project_id: UUID, db: Database) -> dict:
    return review_data(db, get_project(project_id, db))


@router.post("/projects/{project_id}/summary-revisions", status_code=201)
def edit(project_id: UUID, data: SummaryEdit, db: Database) -> dict:
    return edit_summary(db, get_project(project_id, db), data)


@router.post("/projects/{project_id}/summary-approval")
def approve(project_id: UUID, data: SummaryApprove, db: Database) -> dict:
    return approve_summary(db, get_project(project_id, db), data)


@router.post("/projects/{project_id}/summary-changes")
def changes(project_id: UUID, data: SummaryChanges, db: Database) -> dict:
    return request_summary_changes(db, get_project(project_id, db), data)
