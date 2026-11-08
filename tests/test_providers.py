import httpx
import pytest

from incident_atlas import providers


def test_responses_api_shape_and_no_secret_leak(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-secret")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    seen = {}
    original = httpx.Client

    def handler(request):
        import json

        seen.update(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-only-secret"
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"abstain":true,"claims":[]}',
                            }
                        ]
                    }
                ],
                "usage": {"input_tokens": 10},
            },
        )

    monkeypatch.setattr(
        providers.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(handler)),
    )
    result, usage = providers.generate(
        "openai", "question", [{"id": "a", "text": "context"}]
    )
    assert result["abstain"] and usage["input_tokens"] == 10
    assert seen["text"]["format"]["strict"] is True
    assert "test-only-secret" not in str(providers.availability())


def test_provider_http_failure_is_sanitized(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-test-value")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    original = httpx.Client
    monkeypatch.setattr(
        providers.httpx,
        "Client",
        lambda **kw: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text="private-test-value")
            )
        ),
    )
    with pytest.raises(providers.ProviderError) as exc:
        providers.generate("openai", "question", [])
    assert "private-test-value" not in str(exc.value)


def test_ollama_uses_loopback_and_structured_schema(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "local-test")
    original = httpx.Client

    def handler(request):
        assert request.url.host == "127.0.0.1"
        return httpx.Response(
            200,
            json={
                "message": {"content": '{"abstain":true,"claims":[]}'},
                "prompt_eval_count": 4,
            },
        )

    monkeypatch.setattr(
        providers.httpx,
        "Client",
        lambda **kw: original(transport=httpx.MockTransport(handler)),
    )
    assert providers.generate("ollama", "question", [])[1]["input_tokens"] == 4
