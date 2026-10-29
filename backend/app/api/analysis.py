from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.analysis_schemas import AnalysisRead, AnswerSubmission, VersionRequest
from app.api.projects import Database, get_project, save_requirement
from app.models import AnalysisVersion, ClarificationAnswer
from app.schemas import RequirementRead, RequirementSubmit
from app.services.analysis import analysis_response, run_analysis
from app.services.document_parser import MAX_UPLOAD_BYTES, DocumentError, parse_document
from app.services.ollama import OllamaClient, get_llm

router = APIRouter()
LLM = Annotated[OllamaClient, Depends(get_llm)]


class CompatibilityProbe(BaseModel):
    ready: Literal[True]


@router.get("/llm/health")
def llm_health(llm: LLM, probe: bool = True) -> dict:
    result = llm.check()
    if probe:
        _, usage = llm.generate(
            CompatibilityProbe, "Return ready=true in the required JSON schema.", {}
        )
        result.update(structured_output_compatible=True, usage=usage.model_dump())
        result["probe_scope"] = "minimal_json_schema"
    else:
        result["structured_output_compatible"] = None
    return result


@router.post("/projects/{project_id}/uploads", status_code=201, response_model=RequirementRead)
def upload(
    project_id: UUID,
    db: Database,
    file: Annotated[UploadFile, File()],
    expected_version: Annotated[int, Form(ge=1)],
):
    try:
        content = file.file.read(MAX_UPLOAD_BYTES + 1)
        text, sources = parse_document(file.filename or "", file.content_type or "", content)
    except DocumentError as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        file.file.close()
    # Reuse the existing intake transaction, with provenance attached before commit.
    return save_requirement(
        project_id,
        RequirementSubmit(text=text, expected_version=expected_version),
        db,
        sources=sources,
    )


@router.post("/projects/{project_id}/analyze", response_model=AnalysisRead)
def analyze(project_id: UUID, data: VersionRequest, db: Database, llm: LLM) -> dict:
    return run_analysis(db, get_project(project_id, db), data.expected_version, llm)


@router.get("/projects/{project_id}/analysis", response_model=AnalysisRead)
def get_analysis(project_id: UUID, db: Database, version: int | None = Query(None, ge=1)) -> dict:
    return analysis_response(db, get_project(project_id, db), version)


@router.get("/projects/{project_id}/analysis/versions")
def analysis_versions(
    project_id: UUID,
    db: Database,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> list[dict]:
    get_project(project_id, db)
    return [
        {"version": r.version, "source_version": r.source_version, "created_at": r.created_at}
        for r in db.scalars(
            select(AnalysisVersion)
            .where(AnalysisVersion.project_id == str(project_id))
            .order_by(AnalysisVersion.version.desc())
            .offset(offset)
            .limit(limit)
        )
    ]


@router.post("/projects/{project_id}/answers", response_model=AnalysisRead)
def answer(project_id: UUID, data: AnswerSubmission, db: Database, llm: LLM) -> dict:
    return run_analysis(db, get_project(project_id, db), data.expected_version, llm, data)


@router.get("/projects/{project_id}/answers/history")
def answer_history(
    project_id: UUID,
    db: Database,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> list[dict]:
    get_project(project_id, db)
    return [
        {
            "question_id": a.question_id,
            "value": a.value,
            "revision": a.revision,
            "analysis_version": a.analysis_version,
            "created_at": a.created_at,
        }
        for a in db.scalars(
            select(ClarificationAnswer)
            .where(ClarificationAnswer.project_id == str(project_id))
            .order_by(ClarificationAnswer.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ]


@router.get("/projects/{project_id}/summary.md", response_class=PlainTextResponse)
def summary_markdown(
    project_id: UUID, db: Database, version: int | None = Query(None, ge=1)
) -> str:
    result = analysis_response(db, get_project(project_id, db), version)
    if result["markdown"] is None:
        raise HTTPException(409, "Resolve blocking clarifications before generating a summary")
    return result["markdown"]
