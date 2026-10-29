from app.analysis_schemas import AnalysisDocument, Answer, AnswerValue, Question, Source


def answer_is_decided(value: AnswerValue) -> bool:
    values = value if isinstance(value, list) else [value]
    undecided = {
        "tbd",
        "not sure",
        "unknown",
        "undecided",
        "not decided",
        "to be decided",
        "to be decided later",
        "decide later",
        "defer",
        "deferred",
    }
    return bool(values) and all(v.strip().casefold().rstrip(".!?") not in undecided for v in values)


def answered(question_id: str, answers: dict) -> bool:
    return question_id in answers and answer_is_decided(answers[question_id])


def validate_sources(document: AnalysisDocument, sources: list[dict]) -> None:
    ids = {Source.model_validate(s).id for s in sources}
    for requirement in document.requirements:
        if not set(requirement.source_refs) <= ids:
            raise ValueError("Unknown source reference")


def active(question: Question, questions: list[Question], answers: dict[str, AnswerValue]) -> bool:
    if not question.condition:
        return True
    parent = next(q for q in questions if q.id == question.condition.question_id)
    if not active(parent, questions, answers):
        return False
    value = answers.get(parent.id)
    values = value if isinstance(value, list) else [value]
    return bool(set(values) & set(question.condition.any_of))


def required_questions(document: AnalysisDocument, answers: dict) -> set[str]:
    """Include unanswered ancestors that can activate a blocking child."""
    needed: set[str] = set()
    by_id = {q.id: q for q in document.questions}
    for q in document.questions:
        if not q.blocking:
            continue
        chain = [q]
        while chain[-1].condition:
            chain.append(by_id[chain[-1].condition.question_id])
        for candidate in reversed(chain):
            if active(candidate, document.questions, answers) and not answered(
                candidate.id, answers
            ):
                needed.add(candidate.id)
                break
    return needed


def question_batch(document: AnalysisDocument, answers: dict, size: int = 5) -> list[Question]:
    needed = required_questions(document, answers)
    pending = [
        q
        for q in document.questions
        if not answered(q.id, answers) and active(q, document.questions, answers)
    ]
    return sorted(pending, key=lambda q: (q.id not in needed, q.priority, q.id))[:size]


def validate_answers(document: AnalysisDocument, current: dict, submitted: list[Answer]) -> None:
    ids = [a.question_id for a in submitted]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate clarification answers")
    by_id = {q.id: q for q in document.questions}
    for answer in submitted:
        q = by_id.get(answer.question_id)
        if q is None or not active(q, document.questions, current):
            raise ValueError("Unknown or inactive clarification question")
        value = answer.value
        if q.type == "multi_select":
            if (
                not isinstance(value, list)
                or not value
                or len(value) != len(set(value))
                or not set(value) <= set(q.options)
            ):
                raise ValueError("Select distinct values from the available options")
        elif not isinstance(value, str) or not value.strip() or len(value) > 10000:
            raise ValueError("Answer must be nonempty text of at most 10000 characters")
        elif q.type != "free_text" and value not in q.options:
            raise ValueError("Answer is not an available option")


def invalidate_descendants(
    document: AnalysisDocument, answers: dict, changed: set[str]
) -> set[str]:
    invalidated: set[str] = set()
    for q in document.questions:
        if q.condition and q.condition.question_id in changed | invalidated:
            changed.add(q.id)
            if q.id in answers:
                invalidated.add(q.id)
    return invalidated
