"""Read-only remote health and JSON-schema probe; never pulls or installs models."""

import argparse
import json

from app.api.analysis import CompatibilityProbe
from app.config import Settings
from app.services.document_parser import text_sources
from app.services.ollama import LLMError, OllamaClient
from app.workflows.ba_graph import graph_definition
from app.workflows.checkpoints import TransactionalSaver


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--no-probe", action="store_true")
    parser.add_argument("--model-info", action="store_true")
    parser.add_argument(
        "--update-probe",
        action="store_true",
        help="Verify deterministic decision incorporation with synthetic data",
    )
    parser.add_argument("--attempts", type=int, choices=[1, 2, 3])
    parser.add_argument(
        "--analysis-probe",
        action="store_true",
        help="Analyze a small synthetic input using the real Phase 2 schema",
    )
    args = parser.parse_args()
    settings = Settings(_env_file=args.env_file)
    if args.attempts:
        settings = settings.model_copy(update={"ollama_max_attempts": args.attempts})
    client = OllamaClient(settings)
    try:
        if not (
            args.update_probe and args.no_probe and not args.analysis_probe and not args.model_info
        ):
            print(json.dumps(client.check()), flush=True)
        if args.model_info:
            print(json.dumps(client.model_info()), flush=True)
        if not args.no_probe:
            value, usage = client.generate(
                CompatibilityProbe, "Return ready=true in the required JSON schema.", {}
            )
            print(
                json.dumps(
                    {"structured_output_compatible": value.ready, "usage": usage.model_dump()}
                ),
                flush=True,
            )
        if args.analysis_probe:
            graph = graph_definition(client, TransactionalSaver())
            config = {"configurable": {"thread_id": "compatibility-probe"}}
            graph.invoke(
                {
                    "sources": text_sources(
                        "Customers need a portal to track order status. "
                        "Security and supported roles have not been decided."
                    ),
                    "submission": None,
                },
                config,
            )
            state = graph.get_state(config)
            print(
                json.dumps(
                    {
                        "analysis_schema_compatible": True,
                        "requirement_count": len(state.values["document"]["requirements"]),
                        "question_count": len(state.values["document"]["questions"]),
                        "paused_for_clarification": bool(state.next),
                        "usage": state.values["usage"],
                    }
                ),
                flush=True,
            )
        if args.update_probe:
            requirement = {
                "id": "R001",
                "category": "functional",
                "text": "The login method has not been decided.",
                "origin": "assumption",
                "source_refs": ["S1"],
            }
            question = {
                "id": "Q001",
                "text": "Which login method is required?",
                "type": "single_select",
                "options": ["Email", "SSO"],
                "blocking": True,
                "priority": 1,
                "related_requirement_ids": ["R001"],
                "condition": None,
            }
            sources = [
                {"id": "S1", "location": "Synthetic input", "text": requirement["text"]},
                {"id": "answer:Q001:v1", "location": "Synthetic answer", "text": "Email"},
            ]
            graph = graph_definition(client, TransactionalSaver())
            config = {"configurable": {"thread_id": "update-compatibility-probe"}}
            graph.invoke(
                {
                    "document": {
                        "grounding_reviewed": True,
                        "overview": "A customer portal.",
                        "requirements": [requirement],
                        "gaps": [],
                        "questions": [question],
                    },
                    "baseline": [requirement],
                    "usage": [],
                    "sources": sources,
                    "answers": {},
                    "answer_refs": {},
                    "submission": {
                        "affected": ["R001"],
                        "answers": {"Q001": "Email"},
                        "answer_refs": {"Q001": "answer:Q001:v1"},
                        "sources": sources,
                    },
                },
                config,
            )
            state = graph.get_state(config).values
            print(
                json.dumps(
                    {
                        "deterministic_update_valid": True,
                        "summary_status": state["summary"]["status"],
                        "decision_count": len(state["summary"]["clarification_decisions"]),
                        "usage": state["usage"],
                    }
                ),
                flush=True,
            )
    except LLMError as exc:
        print(json.dumps({"code": exc.code, "detail": exc.message}), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
