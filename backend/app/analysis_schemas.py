"""LLM output is untrusted: schemas and cross-reference checks are deterministic."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.workflows.state import WorkflowState

Category = Literal[
    "business_goal",
    "scope",
    "user_role",
    "functional",
    "non_functional",
    "business_rule",
    "constraint",
    "dependency",
    "assumption",
]
AnswerValue = str | list[str]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Source(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=100000)


class ExtractedRequirement(StrictModel):
    id: str = Field(pattern=r"^R[0-9]{3,6}$")
    category: Category
    text: str = Field(min_length=1, max_length=10000)
    origin: Literal["stated", "assumption", "customer_answer"]
    source_refs: list[str] = Field(max_length=200)

    @model_validator(mode="after")
    def provenance(self):
        if self.origin != "assumption" and not self.source_refs:
            raise ValueError("Stated requirements need source references")
        if self.category == "assumption" and self.origin != "assumption":
            raise ValueError("Assumptions must be labelled as assumptions")
        return self


class Condition(StrictModel):
    question_id: str
    any_of: list[str] = Field(min_length=1, max_length=20)


class Question(StrictModel):
    id: str = Field(pattern=r"^Q[0-9]{3,6}$")
    text: str = Field(min_length=1, max_length=2000)
    type: Literal["single_select", "multi_select", "yes_no", "free_text"]
    options: list[str] = Field(max_length=20)
    related_requirement_ids: list[str] = Field(min_length=1, max_length=100)
    blocking: bool
    priority: int = Field(ge=1, le=5)
    condition: Condition | None

    @model_validator(mode="after")
    def choices(self):
        if len(self.options) != len(set(self.options)) or any(not x.strip() for x in self.options):
            raise ValueError("Options must be distinct and nonempty")
        if self.type in {"single_select", "multi_select"} and len(self.options) < 2:
            raise ValueError("Select questions need at least two options")
        if self.type == "free_text" and self.options:
            raise ValueError("Free text has no options")
        if self.type == "yes_no" and self.options != ["yes", "no"]:
            raise ValueError("Yes/no options must be yes and no")
        return self


class Gap(StrictModel):
    kind: Literal["missing", "ambiguity", "conflict", "business_rule", "security", "behavior"]
    description: str = Field(min_length=1, max_length=3000)
    related_requirement_ids: list[str] = Field(min_length=1)
    question_ids: list[str] = Field(min_length=1)


class AnalysisDocument(StrictModel):
    overview: str = Field(min_length=1, max_length=5000)
    requirements: list[ExtractedRequirement] = Field(min_length=1, max_length=500)
    gaps: list[Gap] = Field(max_length=100)
    questions: list[Question] = Field(max_length=50)

    @model_validator(mode="after")
    def references(self):
        ids = [r.id for r in self.requirements]
        qids = [q.id for q in self.questions]
        if len(ids) != len(set(ids)) or len(qids) != len(set(qids)):
            raise ValueError("Duplicate requirement or question IDs")
        seen: set[str] = set()
        for q in self.questions:
            if not set(q.related_requirement_ids) <= set(ids):
                raise ValueError("Unknown related requirement")
            if q.condition:
                if q.condition.question_id not in seen:
                    raise ValueError("Conditional parents must precede children; cycles forbidden")
                parent = next(p for p in self.questions if p.id == q.condition.question_id)
                if parent.type != "free_text" and not set(q.condition.any_of) <= set(
                    parent.options
                ):
                    raise ValueError("Condition refers to unknown options")
            seen.add(q.id)
        for gap in self.gaps:
            if not set(gap.related_requirement_ids) <= set(ids):
                raise ValueError("Unknown gap requirement")
            if not set(gap.question_ids) <= set(qids):
                raise ValueError("Unknown gap question")
        return self


class RequirementUpdate(StrictModel):
    id: str = Field(pattern=r"^R[0-9]{3,6}$")
    text: str = Field(min_length=1, max_length=10000)
    resolved_category: Category | None = None


class RequirementPatch(StrictModel):
    requirements: list[RequirementUpdate] = Field(min_length=1, max_length=500)


class Answer(StrictModel):
    question_id: str
    value: AnswerValue


class VersionRequest(StrictModel):
    expected_version: int = Field(ge=1)


class AnswerSubmission(VersionRequest):
    answers: list[Answer] = Field(min_length=1, max_length=5)


class ClarificationDecision(StrictModel):
    question_id: str
    question: str
    answer: AnswerValue
    related_requirement_ids: list[str]


class DraftSummary(StrictModel):
    status: Literal["DRAFT"] = "DRAFT"
    project_overview: str
    sections: dict[str, list[ExtractedRequirement]]
    open_non_blocking_questions: list[Question]
    clarification_decisions: list[ClarificationDecision] = Field(default_factory=list)


class Usage(StrictModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    attempts: int = Field(ge=1)


class AnalysisRead(StrictModel):
    project_id: str
    project_version: int
    state: WorkflowState
    version: int
    source_version: int
    document: AnalysisDocument
    initial_description: DraftSummary
    sources: list[Source]
    summary: DraftSummary | None
    markdown: str | None
    usage: list[Usage]
    answers: dict[str, AnswerValue]
    questions: list[Question]
    answered_questions: list[Question]
