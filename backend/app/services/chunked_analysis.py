"""Bounded document chunks, stable ID remapping and cross-chunk gap analysis."""

from copy import deepcopy

from pydantic import Field

from app.analysis_schemas import AnalysisDocument, Gap, Question, Source, StrictModel
from app.services.business_quality import normalized
from app.services.llm import StructuredLLM
from app.services.ollama import LLMError
from app.services.validation import validate_sources

CHUNK_CHARS = 6000


class ConsolidatedFindings(StrictModel):
    overview: str = Field(min_length=1, max_length=5000)
    gaps: list[Gap] = Field(max_length=100)
    questions: list[Question] = Field(max_length=50)


def chunk_sources(sources: list[dict], limit: int = CHUNK_CHARS) -> list[list[dict]]:
    if limit < 100:
        raise ValueError("Chunk limit must be at least 100 characters")
    chunks, current, size = [], [], 0
    for source in sources:
        original = Source.model_validate(source)
        parts = [original.text[i : i + limit] for i in range(0, len(original.text), limit)]
        for index, text in enumerate(parts, 1):
            if not text.strip():
                continue
            item = original.model_dump()
            if len(parts) > 1:
                item.update(
                    id=f"{original.id}:p{index}", location=f"{original.location}, part {index}"
                )
            item["text"] = text
            if current and size + len(text) > limit:
                chunks.append(current)
                current, size = [], 0
            current.append(item)
            size += len(text)
    if current:
        chunks.append(current)
    if not chunks or len(chunks) > 32:
        raise LLMError("document_size", "Document must yield between 1 and 32 bounded chunks.")
    return chunks


def merge_documents(documents: list[AnalysisDocument]) -> AnalysisDocument:
    requirements, questions, gaps = [], [], []
    req_keys, q_keys = {}, {}
    for document in documents:
        rmap, qmap = {}, {}
        for requirement in document.requirements:
            key = (normalized(requirement.text), requirement.category, requirement.origin)
            if key in req_keys:
                stored = req_keys[key]
                stored["source_refs"] = list(
                    dict.fromkeys([*stored["source_refs"], *requirement.source_refs])
                )
            else:
                stored = requirement.model_dump()
                stored["id"] = f"R{len(requirements) + 1:03}"
                requirements.append(stored)
                req_keys[key] = stored
            rmap[requirement.id] = stored["id"]
        for question in document.questions:
            item = question.model_dump()
            item["related_requirement_ids"] = list(
                dict.fromkeys(rmap[rid] for rid in question.related_requirement_ids)
            )
            if item["condition"]:
                item["condition"]["question_id"] = qmap[item["condition"]["question_id"]]
            key = (
                normalized(question.text),
                question.type,
                tuple(question.options),
                str(item["condition"]),
            )
            if key in q_keys:
                stored = q_keys[key]
                stored["related_requirement_ids"] = list(
                    dict.fromkeys(
                        [*stored["related_requirement_ids"], *item["related_requirement_ids"]]
                    )
                )
                stored["blocking"] = stored["blocking"] or item["blocking"]
                stored["priority"] = min(stored["priority"], item["priority"])
            else:
                item["id"] = f"Q{len(questions) + 1:03}"
                questions.append(item)
                q_keys[key] = item
                stored = item
            qmap[question.id] = stored["id"]
        for gap in document.gaps:
            item = gap.model_dump()
            item["related_requirement_ids"] = list(
                dict.fromkeys(rmap[rid] for rid in gap.related_requirement_ids)
            )
            item["question_ids"] = list(dict.fromkeys(qmap[qid] for qid in gap.question_ids))
            if item not in gaps:
                gaps.append(item)
    if len(requirements) > 500 or len(questions) > 50 or len(gaps) > 100:
        raise LLMError(
            "analysis_size", "Extracted content exceeds project limits; split the project scope."
        )
    return AnalysisDocument(
        overview=documents[0].overview, requirements=requirements, questions=questions, gaps=gaps
    )


def extract_chunked(llm: StructuredLLM, sources: list[dict], prompt: str):
    chunks = chunk_sources(sources)
    documents, usage = [], []
    for index, chunk in enumerate(chunks, 1):
        document, call = llm.generate(AnalysisDocument, prompt, {"sources": chunk})
        try:
            validate_sources(document, chunk)
        except ValueError:
            raise LLMError("invalid_output", "Extraction cited an unknown source.") from None
        if any(r.origin == "customer_answer" for r in document.requirements):
            raise LLMError("invalid_output", "Initial extraction cannot contain customer answers.")
        documents.append(document)
        usage.append(
            {
                **call.model_dump(),
                "operation": "extraction" if len(chunks) == 1 else f"extraction_chunk_{index}",
            }
        )
    merged = documents[0] if len(documents) == 1 else merge_documents(documents)
    if len(documents) > 1:
        # Detect contradictions between chunks, not just independently within each chunk.
        findings, call = llm.generate(
            ConsolidatedFindings,
            "Review all normalized requirements together for cross-section conflicts and gaps. "
            "Preserve existing question IDs and questions. "
            "Add only relevant nonduplicate questions; never change requirement IDs "
            "or decide missing business facts. Return all gaps/questions.",
            {
                "requirements": [r.model_dump() for r in merged.requirements],
                "existing_questions": [q.model_dump() for q in merged.questions],
                "existing_gaps": [g.model_dump() for g in merged.gaps],
            },
        )
        raw = deepcopy(merged.model_dump())
        raw.update(
            overview=findings.overview,
            gaps=[g.model_dump() for g in findings.gaps],
            questions=[q.model_dump() for q in findings.questions],
        )
        old = {q.id: q.model_dump() for q in merged.questions}
        new = {q.id: q.model_dump() for q in findings.questions}
        if any(new.get(qid) != question for qid, question in old.items()):
            raise LLMError(
                "invalid_consolidation", "Cross-chunk analysis changed an existing question."
            )
        try:
            merged = AnalysisDocument.model_validate(raw)
        except ValueError:
            raise LLMError(
                "invalid_consolidation", "Cross-chunk analysis failed validation."
            ) from None
        usage.append({**call.model_dump(), "operation": "cross_chunk_conflict_analysis"})
    return merged, [item for chunk in chunks for item in chunk], usage
