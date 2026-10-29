import httpx
import pytest
from pydantic import BaseModel

from app.config import Settings
from app.services.ollama import LLMError, OllamaClient, generation_schema


class Output(BaseModel):
    required: str


def settings(**kwargs):
    return Settings(
        _env_file=None,
        ollama_base_url="http://remote.example:11434",
        ollama_model="existing-model",
        **kwargs,
    )


def test_remote_unavailable_retries_are_bounded(monkeypatch):
    calls = []

    def unavailable(request):
        calls.append(request)
        raise httpx.ConnectError("sensitive internal URL must not leak")

    monkeypatch.setattr("app.services.ollama.time.sleep", lambda _: None)
    llm = OllamaClient(settings(), httpx.MockTransport(unavailable))
    with pytest.raises(LLMError) as error:
        llm.check()
    assert error.value.code == "unavailable"
    assert "sensitive" not in str(error.value)
    assert len(calls) == 3


def test_timeout(monkeypatch):
    monkeypatch.setattr("app.services.ollama.time.sleep", lambda _: None)

    def timeout(request):
        raise httpx.ReadTimeout("secret")

    with pytest.raises(LLMError) as error:
        OllamaClient(settings(ollama_max_attempts=1), httpx.MockTransport(timeout)).check()
    assert error.value.code == "timeout"


def test_model_unavailable():
    llm = OllamaClient(
        settings(),
        httpx.MockTransport(
            lambda _: httpx.Response(200, json={"models": [{"name": "different-model"}]})
        ),
    )
    with pytest.raises(LLMError) as error:
        llm.check()
    assert error.value.code == "model_unavailable"


@pytest.mark.parametrize("content", ["not json", "{}", '{"required": null}'])
def test_invalid_json_and_missing_fields(content):
    llm = OllamaClient(
        settings(),
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "done": True,
                    "message": {"content": content},
                    "prompt_eval_count": 2,
                    "eval_count": 3,
                },
            )
        ),
    )
    with pytest.raises(LLMError) as error:
        llm.generate(Output, "instructions", {})
    assert error.value.code == "invalid_output"


def test_structured_request_and_usage():
    def server(request):
        import json

        body = json.loads(request.content)
        assert request.url.path == "/api/chat"
        assert body["format"] == Output.model_json_schema()
        assert body["stream"] is False
        assert body["options"]["temperature"] == 0
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {"content": '{"required":"ok"}'},
                "prompt_eval_count": 11,
                "eval_count": 7,
            },
        )

    value, usage = OllamaClient(settings(), httpx.MockTransport(server)).generate(Output, "", {})
    assert value.required == "ok"
    assert usage.input_tokens == 11 and usage.output_tokens == 7
    assert usage.attempts == 1 and usage.latency_ms >= 0


@pytest.mark.parametrize(
    "status,code", [(400, "model_incompatible"), (404, "model_unavailable"), (401, "access_denied")]
)
def test_remote_error_sanitization(status, code):
    llm = OllamaClient(
        settings(),
        httpx.MockTransport(
            lambda _: httpx.Response(status, json={"error": "secret server details"})
        ),
    )
    with pytest.raises(LLMError) as error:
        llm.generate(Output, "", {})
    assert error.value.code == code
    assert "secret" not in str(error.value)


def test_unconfigured_remote():
    with pytest.raises(LLMError) as error:
        OllamaClient(Settings(_env_file=None)).check()
    assert error.value.code == "configuration"


def test_copied_endpoint_url_is_normalized():
    config = settings().model_copy(
        update={"ollama_base_url": "http://remote.example/prefix/api/tags"}
    )

    def server(request):
        assert request.url.path == "/prefix/api/tags"
        return httpx.Response(200, json={"models": [{"name": "existing-model:latest"}]})

    assert OllamaClient(config, httpx.MockTransport(server)).check()["model_available"]


def test_transient_failure_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.services.ollama.time.sleep", lambda _: None)
    calls = []

    def server(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {"content": '{"required":"ok"}'},
                "prompt_eval_count": 1,
                "eval_count": 2,
            },
        )

    _, usage = OllamaClient(settings(), httpx.MockTransport(server)).generate(Output, "", {})
    assert usage.attempts == 2


def test_compact_generation_grammar_preserves_python_limits():
    from app.analysis_schemas import ExtractedRequirement

    schema = generation_schema(ExtractedRequirement)
    assert "maxLength" not in schema["properties"]["text"]
    assert schema["properties"]["id"]["pattern"] == r"^R[0-9]{3,6}$"
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtractedRequirement.model_validate(
            {
                "id": "R001",
                "category": "functional",
                "text": "x" * 10001,
                "origin": "stated",
                "source_refs": ["S1"],
            }
        )


def test_generation_read_timeout_is_not_repeated(monkeypatch):
    monkeypatch.setattr("app.services.ollama.time.sleep", lambda _: None)
    calls = []

    def server(request):
        calls.append(request)
        raise httpx.ReadTimeout("still generating")

    with pytest.raises(LLMError) as error:
        OllamaClient(settings(), httpx.MockTransport(server)).generate(Output, "", {})
    assert error.value.code == "timeout"
    assert len(calls) == 1


def test_generation_latency_controls():
    import json

    def server(request):
        body = json.loads(request.content)
        assert body["think"] == "low"
        assert body["options"]["num_predict"] == 2048
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {"content": '{"required":"ok"}'},
                "prompt_eval_count": 1,
                "eval_count": 2,
            },
        )

    config = settings(ollama_think="low", ollama_num_predict=2048)
    OllamaClient(config, httpx.MockTransport(server)).generate(Output, "", {})
