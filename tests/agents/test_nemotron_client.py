import json

import httpx
from openai import OpenAI
import pytest

from backend.agents.nemotron import BASE_URL, MODEL, NemotronClient, NemotronConfig, NemotronError


def test_exact_nvidia_request_format_and_no_streaming():
    seen = []

    def transport(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "test-response", "object": "chat.completion", "created": 0,
            "model": MODEL, "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": "{}"}}]})

    sdk = OpenAI(api_key="unit-test-key", base_url=BASE_URL, max_retries=0,
                 http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    client = NemotronClient(NemotronConfig(api_key="unit-test-key"), sdk)
    try:
        client.complete([{"role": "user", "content": "test"}], [], 10)
    finally:
        client.close()
    payload = json.loads(seen[0].content)
    assert str(seen[0].url) == BASE_URL + "/chat/completions"
    assert payload["model"] == MODEL and payload["stream"] is False
    assert payload["tool_choice"] == "auto"
    assert payload["chat_template_kwargs"]["enable_thinking"] is True
    assert seen[0].headers["authorization"] == "Bearer unit-test-key"


@pytest.mark.parametrize("status,code", [(401, "PROVIDER_AUTHENTICATION"), (403, "PROVIDER_ACCESS"),
                                       (429, "PROVIDER_RATE_LIMIT"), (500, "PROVIDER_ERROR")])
def test_provider_errors_are_safe_and_not_retried(status, code):
    calls = []
    def transport(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "unit-test-key must not escape"}})
    sdk = OpenAI(api_key="unit-test-key", base_url=BASE_URL, max_retries=0,
                 http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    client = NemotronClient(NemotronConfig(api_key="unit-test-key"), sdk)
    try:
        with pytest.raises(NemotronError) as failure:
            client.complete([], [], 10)
        assert failure.value.code == code and "unit-test-key" not in str(failure.value)
        assert len(calls) == 1
    finally:
        client.close()


def test_configuration_missing_key_and_invalid_limits(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(NemotronError, match="Configure NVIDIA_API_KEY"):
        NemotronConfig.from_environment()
    monkeypatch.setenv("NVIDIA_API_KEY", "unit-test-key")
    monkeypatch.setenv("NEMOTRON_REQUEST_TIMEOUT_SECONDS", "nan")
    with pytest.raises(NemotronError, match="Invalid Nemotron"):
        NemotronConfig.from_environment()
