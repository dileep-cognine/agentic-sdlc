import pytest
from test_analysis import document

from app.analysis_schemas import AnalysisDocument, Usage
from app.services.chunked_analysis import (
    ConsolidatedFindings,
    chunk_sources,
    extract_chunked,
    merge_documents,
)
from app.services.ollama import LLMError


def test_chunks_are_bounded_and_retain_source_locations():
    chunks = chunk_sources([{"id": "S1", "location": "page 1", "text": "a" * 250}], 100)
    assert [sum(len(s["text"]) for s in c) for c in chunks] == [100, 100, 50]
    assert chunks[2][0]["id"] == "S1:p3"
    assert chunks[2][0]["location"] == "page 1, part 3"


def test_merge_preserves_condition_links_and_deduplicates():
    first = AnalysisDocument.model_validate(document())
    other = document()
    other["requirements"][0]["source_refs"] = ["S2"]
    result = merge_documents([first, AnalysisDocument.model_validate(other)])
    assert len(result.requirements) == 2
    assert result.requirements[0].source_refs == ["S1", "S2"]
    assert len(result.questions) == 2
    assert result.questions[1].condition.question_id == "Q001"


def test_chunk_limit_rejects_without_silent_truncation():
    with pytest.raises(LLMError):
        chunk_sources([{"id": "S1", "location": "text", "text": "a" * 3300}], 100)


@pytest.mark.parametrize("drop_question", [False, True])
def test_cross_chunk_review_preserves_questions_and_records_conflicts(drop_question):
    class ChunkLLM:
        def generate(self, schema, instructions, payload):
            if schema is AnalysisDocument:
                value = document()
                value["requirements"][0]["source_refs"] = [payload["sources"][0]["id"]]
            else:
                assert schema is ConsolidatedFindings
                value = {
                    "overview": "Combined portal",
                    "questions": payload["existing_questions"],
                    "gaps": payload["existing_gaps"]
                    + [
                        {
                            "kind": "conflict",
                            "description": "Cross-section policy conflict",
                            "related_requirement_ids": ["R001"],
                            "question_ids": ["Q001"],
                        }
                    ],
                }
                if drop_question:
                    value["questions"] = []
            return schema.model_validate(value), Usage(
                input_tokens=10, output_tokens=10, latency_ms=1, attempts=1
            )

    sources = [{"id": "S1", "location": "text", "text": "a" * 6001}]
    if drop_question:
        with pytest.raises(LLMError):
            extract_chunked(ChunkLLM(), sources, "Extract")
    else:
        result, references, usage = extract_chunked(ChunkLLM(), sources, "Extract")
        assert any(g.kind == "conflict" for g in result.gaps)
        assert result.requirements[0].source_refs == ["S1:p1", "S1:p2"]
        assert len(references) == 2
        assert usage[-1]["operation"] == "cross_chunk_conflict_analysis"
