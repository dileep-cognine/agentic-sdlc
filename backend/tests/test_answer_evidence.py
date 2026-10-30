import pytest
from test_analysis import document

from app.analysis_schemas import AnalysisDocument, Answer, AnswerReviewBatch, Usage
from app.services.answer_review import assess_answers
from app.services.ollama import LLMError


class EvidenceLLM:
    def __init__(self, quotes):
        self.quotes = quotes
        self.calls = []

    def generate(self, schema, prompt, payload):
        self.calls.append(payload)
        quote = self.quotes[min(len(self.calls) - 1, len(self.quotes) - 1)]
        return AnswerReviewBatch.model_validate(
            {
                "assessments": [
                    {
                        "question_id": "Q001",
                        "status": "VALID",
                        "reason": "Clear policy.",
                        "suggested_clarification": "",
                        "open_details": [],
                        "requirements": [
                            {
                                "key": "customer_login",
                                "title": "Customer login",
                                "text": "Customers shall use email and password.",
                                "category": "functional",
                                "source_excerpt": quote,
                            }
                        ],
                    }
                ]
            }
        ), Usage(input_tokens=10, output_tokens=20, latency_ms=3, attempts=1)


def assess(model, value):
    return assess_answers(
        model,
        AnalysisDocument.model_validate(document()),
        [Answer(question_id="Q001", value=value)],
    )


def test_formatting_difference_restores_actual_answer_quote_without_retry():
    model = EvidenceLLM(["email and password"])
    reviews, usage = assess(model, "Customers use EMAIL\n and  password.")
    assert reviews["Q001"]["requirements"][0]["source_excerpt"] == "EMAIL\n and  password"
    assert len(model.calls) == 1
    assert usage[0]["operation"] == "answer_review"


def test_paraphrased_evidence_gets_one_targeted_repair_and_tracks_usage():
    model = EvidenceLLM(["email/password", "email and password"])
    reviews, usage = assess(model, "Customers use email and password.")
    assert reviews["Q001"]["status"] == "VALID"
    assert len(model.calls) == 2
    assert usage[1]["operation"] == "answer_evidence_repair"
    assert "sources" not in model.calls[1]  # Never reprocess the original document.


def test_invented_evidence_is_rejected_after_bounded_repair():
    model = EvidenceLLM(["Google SSO"])
    with pytest.raises(LLMError, match="after one repair"):
        assess(model, "Customers use email and password.")
    assert len(model.calls) == 2


def test_quote_cannot_join_separate_selected_options():
    model = EvidenceLLM(["Email Password"])
    with pytest.raises(LLMError):
        assess(model, ["Email", "Password"])
