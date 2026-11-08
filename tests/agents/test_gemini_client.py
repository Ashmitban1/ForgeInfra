import json

import httpx
import pytest

from backend.agents.gemini import BASE_URL, MODEL, GeminiClient, GeminiConfig, GeminiError
from backend.agents.review_schemas import ReviewConclusion


def response_body(text='{}', finish='STOP'):
    return {"responseId": "test-google-response", "modelVersion": MODEL,
            "candidates": [{"finishReason": finish, "content": {"parts": [
                {"text": "private reasoning must not escape", "thought": True}, {"text": text},
            ]}}], "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 10, "totalTokenCount": 30}}


def test_gemini_native_json_request_and_safe_metadata():
    seen = []
    def transport(request):
        seen.append(request)
        return httpx.Response(200, json=response_body())
    client = GeminiClient(GeminiConfig(api_key='test-gemini-secret'), httpx.MockTransport(transport))
    try:
        text, metadata = client.review({'incident': 'synthetic'}, 'review evidence', ReviewConclusion.model_json_schema())
    finally:
        client.close()
    request = seen[0]
    assert str(request.url) == BASE_URL + '/models/' + MODEL + ':generateContent'
    assert request.headers['x-goog-api-key'] == 'test-gemini-secret'
    assert 'test-gemini-secret' not in str(request.url) + request.content.decode()
    payload = json.loads(request.content)
    assert payload['generationConfig']['responseMimeType'] == 'application/json'
    assert payload['generationConfig']['responseJsonSchema']['additionalProperties'] is False
    assert 'tools' not in payload and len(seen) == 1
    assert text == '{}' and 'private reasoning' not in str(metadata)
    assert metadata['response_id'] == 'test-google-response' and metadata['usage']['totalTokenCount'] == 30


@pytest.mark.parametrize('status,code', [(400, 'PROVIDER_REQUEST_REJECTED'), (401, 'PROVIDER_AUTHENTICATION'),
    (403, 'PROVIDER_ACCESS'), (404, 'PROVIDER_MODEL_UNAVAILABLE'), (429, 'PROVIDER_RATE_LIMIT'), (500, 'PROVIDER_ERROR')])
def test_gemini_provider_failures_are_safe_and_not_retried(status, code):
    seen = []
    def transport(request):
        seen.append(request)
        return httpx.Response(status, json={'error': {'message': 'test-gemini-secret must stay private'}})
    client = GeminiClient(GeminiConfig(api_key='test-gemini-secret'), httpx.MockTransport(transport))
    try:
        with pytest.raises(GeminiError) as error:
            client.review({}, 'test', {})
        assert error.value.code == code and 'test-gemini-secret' not in str(error.value)
        assert len(seen) == 1
    finally:
        client.close()


@pytest.mark.parametrize('finish,code', [('MAX_TOKENS', 'MODEL_OUTPUT_TRUNCATED'), ('SAFETY', 'MODEL_OUTPUT_BLOCKED')])
def test_incomplete_gemini_output_cannot_be_a_review(finish, code):
    client = GeminiClient(GeminiConfig(api_key='test-key'), httpx.MockTransport(
        lambda request: httpx.Response(200, json=response_body(finish=finish))))
    try:
        with pytest.raises(GeminiError) as error:
            client.review({}, 'test', {})
        assert error.value.code == code
    finally:
        client.close()


def test_gemini_timeout_has_no_provider_body():
    def transport(request):
        raise httpx.ReadTimeout('test-gemini-secret', request=request)
    client = GeminiClient(GeminiConfig(api_key='test-gemini-secret'), httpx.MockTransport(transport))
    try:
        with pytest.raises(GeminiError) as error:
            client.review({}, 'test', {})
        assert error.value.code == 'PROVIDER_TIMEOUT' and 'test-gemini-secret' not in str(error.value)
    finally:
        client.close()


@pytest.mark.parametrize('name,value', [('GEMINI_MODEL', '../../unsafe'), ('GEMINI_REQUEST_TIMEOUT_SECONDS', 'nan'),
    ('GEMINI_MAX_TOKENS', '999999')])
def test_gemini_configuration_validation(monkeypatch, name, value):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key')
    monkeypatch.setenv(name, value)
    with pytest.raises(GeminiError, match='Invalid Gemini'):
        GeminiConfig.from_environment()


def test_missing_gemini_key_is_not_a_fake_provider(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    with pytest.raises(GeminiError, match='Configure GEMINI_API_KEY'):
        GeminiConfig.from_environment()
