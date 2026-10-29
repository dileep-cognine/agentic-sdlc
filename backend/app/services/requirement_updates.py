"""Deterministic metadata ownership for LLM-authored requirement text updates."""

from app.analysis_schemas import ExtractedRequirement, Question, RequirementPatch


class PatchValidationError(ValueError):
    pass


def merge_requirement_patch(
    baseline: list[dict], patch: RequirementPatch, questions: list[Question], refs: dict[str, str]
) -> list[dict]:
    ids = [r.id for r in patch.requirements]
    expected = {r["id"] for r in baseline}
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise PatchValidationError("requirement_ids_changed")
    updates = {r.id: r for r in patch.requirements}
    merged = []
    for original in baseline:
        update = updates[original["id"]]
        category = original["category"]
        if update.resolved_category is not None:
            if category != "assumption" and update.resolved_category != category:
                raise PatchValidationError("unrelated_category_change")
            category = update.resolved_category
        answer_refs = [refs[q.id] for q in questions if original["id"] in q.related_requirement_ids]
        if not answer_refs:
            raise PatchValidationError("update_has_no_customer_answer")
        # These fields describe the actual inputs used, not model-generated citations.
        requirement = ExtractedRequirement(
            id=original["id"],
            text=update.text,
            category=category,
            origin="assumption" if category == "assumption" else "customer_answer",
            source_refs=list(dict.fromkeys([*original["source_refs"], *answer_refs])),
        )
        merged.append(requirement.model_dump())
    return merged
