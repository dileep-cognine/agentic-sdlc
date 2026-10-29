from enum import StrEnum
from typing import TypedDict


class WorkflowState(StrEnum):
    INTAKE = "INTAKE"
    ANALYZING = "ANALYZING"
    AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION"
    REQUIREMENTS_REVIEW = "REQUIREMENTS_REVIEW"
    AWAITING_ARCHITECTURE = "AWAITING_ARCHITECTURE"
    ARCHITECTURE_REVIEW = "ARCHITECTURE_REVIEW"
    GENERATING_BA_ARTIFACTS = "GENERATING_BA_ARTIFACTS"
    VALIDATING = "VALIDATING"
    FINAL_REVIEW = "FINAL_REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.INTAKE: frozenset({WorkflowState.ANALYZING, WorkflowState.FAILED}),
    WorkflowState.ANALYZING: frozenset(
        {
            WorkflowState.AWAITING_CLARIFICATION,
            WorkflowState.REQUIREMENTS_REVIEW,
            WorkflowState.FAILED,
        }
    ),
    WorkflowState.AWAITING_CLARIFICATION: frozenset(
        {WorkflowState.ANALYZING, WorkflowState.FAILED}
    ),
    WorkflowState.REQUIREMENTS_REVIEW: frozenset(
        {WorkflowState.ANALYZING, WorkflowState.AWAITING_ARCHITECTURE, WorkflowState.FAILED}
    ),
    WorkflowState.AWAITING_ARCHITECTURE: frozenset(
        {WorkflowState.ARCHITECTURE_REVIEW, WorkflowState.FAILED}
    ),
    WorkflowState.ARCHITECTURE_REVIEW: frozenset(
        {
            WorkflowState.AWAITING_ARCHITECTURE,
            WorkflowState.GENERATING_BA_ARTIFACTS,
            WorkflowState.FAILED,
        }
    ),
    WorkflowState.GENERATING_BA_ARTIFACTS: frozenset(
        {WorkflowState.VALIDATING, WorkflowState.FAILED}
    ),
    WorkflowState.VALIDATING: frozenset(
        {WorkflowState.GENERATING_BA_ARTIFACTS, WorkflowState.FINAL_REVIEW, WorkflowState.FAILED}
    ),
    WorkflowState.FINAL_REVIEW: frozenset(
        {WorkflowState.GENERATING_BA_ARTIFACTS, WorkflowState.COMPLETED, WorkflowState.FAILED}
    ),
    WorkflowState.COMPLETED: frozenset(),
    WorkflowState.FAILED: frozenset(),
}

HUMAN_GATES = {
    (WorkflowState.REQUIREMENTS_REVIEW, WorkflowState.AWAITING_ARCHITECTURE),
    (WorkflowState.ARCHITECTURE_REVIEW, WorkflowState.GENERATING_BA_ARTIFACTS),
    (WorkflowState.FINAL_REVIEW, WorkflowState.COMPLETED),
}


def validate_transition(
    current: WorkflowState, target: WorkflowState, *, human_approved: bool = False
) -> None:
    if target not in TRANSITIONS[current]:
        raise ValueError("Transition is not permitted")
    if (current, target) in HUMAN_GATES and not human_approved:
        raise ValueError("Explicit human approval is required")


class BAWorkflowContext(TypedDict):
    project_id: str
    project_version: int
    state: str
    requirement_version: int | None
