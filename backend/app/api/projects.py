from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project, RequirementVersion, WorkflowCheckpoint, now
from app.schemas import ProjectCreate, ProjectRead, RequirementRead, RequirementSubmit
from app.services.document_parser import DocumentError, normalize, text_sources
from app.workflows.state import WorkflowState

router = APIRouter()
Database = Annotated[Session, Depends(get_db)]


def checkpoint(db: Session, project: Project, requirement_version: int | None) -> None:
    db.add(
        WorkflowCheckpoint(
            project_id=project.id,
            project_version=project.version,
            state=project.state,
            payload={
                "project_id": project.id,
                "project_version": project.version,
                "state": project.state,
                "requirement_version": requirement_version,
            },
        )
    )


@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(data: ProjectCreate, db: Database) -> Project:
    project = Project(**data.model_dump())
    db.add(project)
    db.flush()
    checkpoint(db, project, None)
    db.commit()
    return project


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(
    db: Database, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
) -> list[Project]:
    return list(
        db.scalars(
            select(Project)
            .order_by(Project.created_at.desc(), Project.id)
            .offset(offset)
            .limit(limit)
        )
    )


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: UUID, db: Database) -> Project:
    project = db.get(Project, str(project_id))
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


@router.post("/projects/{project_id}/requirements", response_model=RequirementRead, status_code=201)
def submit_requirement(
    project_id: UUID, data: RequirementSubmit, db: Database
) -> RequirementVersion:
    return save_requirement(project_id, data, db)


def save_requirement(
    project_id: UUID, data: RequirementSubmit, db: Session, sources: list[dict] | None = None
) -> RequirementVersion:
    try:
        text = normalize(data.text)
    except DocumentError as exc:
        raise HTTPException(422, str(exc)) from None
    project = get_project(project_id, db)
    if project.state != WorkflowState.INTAKE:
        raise HTTPException(409, "Requirements can only be submitted during INTAKE")
    result = db.execute(
        update(Project)
        .where(
            Project.id == project.id,
            Project.version == data.expected_version,
            Project.state == WorkflowState.INTAKE,
        )
        .values(version=Project.version + 1, updated_at=now())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Project version changed; reload before submitting")
    db.refresh(project)
    version = (
        db.scalar(
            select(func.max(RequirementVersion.version)).where(
                RequirementVersion.project_id == project.id
            )
        )
        or 0
    ) + 1
    requirement = RequirementVersion(
        project_id=project.id,
        requirement_id=f"REQ-{project.id}",
        version=version,
        text=text,
        source_data=sources or text_sources(text),
    )
    db.add(requirement)
    checkpoint(db, project, version)
    db.commit()
    return requirement


@router.get("/projects/{project_id}/requirements", response_model=list[RequirementRead])
def list_requirements(
    project_id: UUID,
    db: Database,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> list[RequirementVersion]:
    get_project(project_id, db)
    return list(
        db.scalars(
            select(RequirementVersion)
            .where(RequirementVersion.project_id == str(project_id))
            .order_by(RequirementVersion.version.desc())
            .offset(offset)
            .limit(limit)
        )
    )
