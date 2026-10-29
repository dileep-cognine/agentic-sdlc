from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.workflows.state import WorkflowState


def now() -> datetime:
    return datetime.now(UTC)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(40), default=WorkflowState.INTAKE.value)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RequirementVersion(Base):
    __tablename__ = "requirement_versions"
    __table_args__ = (UniqueConstraint("project_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement_id: Mapped[str] = mapped_column(String(50))
    version: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    source_data: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkflowCheckpoint(Base):
    __tablename__ = "workflow_checkpoints"
    __table_args__ = (UniqueConstraint("project_id", "project_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    project_version: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AnalysisVersion(Base):
    __tablename__ = "analysis_versions"
    __table_args__ = (UniqueConstraint("project_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    source_version: Mapped[int] = mapped_column(Integer)
    document: Mapped[dict] = mapped_column(JSON)
    answers: Mapped[dict] = mapped_column(JSON)
    sources: Mapped[list] = mapped_column(JSON)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ClarificationAnswer(Base):
    __tablename__ = "clarification_answers"
    __table_args__ = (UniqueConstraint("project_id", "question_id", "revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    question_id: Mapped[str] = mapped_column(String(20))
    revision: Mapped[int] = mapped_column(Integer)
    analysis_version: Mapped[int] = mapped_column(Integer)
    value: Mapped[str | list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GraphRuntime(Base):
    __tablename__ = "graph_runtime"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
