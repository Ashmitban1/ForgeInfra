"""Bounded Gemini REST client; keys are headers, never evidence or URL parameters."""

from dataclasses import dataclass, field
import json
import math
import os
import re
import time

import httpx

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
MODEL = "gemini-3.5-flash-lite"


class GeminiError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str = field(repr=False)
    model: str = MODEL
    request_timeout: float = 90
    max_tokens: int = 8192

    @classmethod
    def from_environment(cls):
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if not key or key in {"GEMINI_API_KEY", "$GEMINI_API_KEY", "YOUR_KEY", "YOUR_GEMINI_API_KEY"}:
            raise GeminiError("NOT_CONFIGURED", "Configure GEMINI_API_KEY in the backend environment")
        try:
            config = cls(
                api_key=key, model=os.getenv("GEMINI_MODEL", MODEL).strip(),
                request_timeout=float(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "90")),
                max_tokens=int(os.getenv("GEMINI_MAX_TOKENS", "8192")),
            )
            if (not re.fullmatch(r"gemini-[a-zA-Z0-9.-]{1,100}", config.model)
                    or not math.isfinite(config.request_timeout) or not 1 <= config.request_timeout <= 120
                    or not 256 <= config.max_tokens <= 16384):
                raise ValueError()
            return config
        except ValueError:
            raise GeminiError("INVALID_CONFIGURATION", "Invalid Gemini model/limits") from None


class GeminiClient:
    def __init__(self, config: GeminiConfig, transport=None):
        self.config = config
        self.http = httpx.Client(timeout=config.request_timeout, transport=transport, follow_redirects=False)

    def review(self, bundle: dict, system_prompt: str, schema: dict) -> tuple[str, dict]:
        content = json.dumps(bundle, allow_nan=False)
        if len(content.encode("utf-8")) > 200_000:
            raise GeminiError("INPUT_TOO_LARGE", "Review evidence exceeds the supported input limit")
        started = time.monotonic()
        try:
            response = self.http.post(
                BASE_URL + "/models/" + self.config.model + ":generateContent",
                headers={"x-goog-api-key": self.config.api_key},
                json={
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"role": "user", "parts": [{"text": content}]}],
                    "generationConfig": {
                        "candidateCount": 1, "maxOutputTokens": self.config.max_tokens,
                        "responseMimeType": "application/json", "responseJsonSchema": schema,
                    },
                },
            )
        except httpx.TimeoutException:
            raise GeminiError("PROVIDER_TIMEOUT", "Gemini request timed out") from None
        except httpx.RequestError:
            raise GeminiError("PROVIDER_UNAVAILABLE", "Gemini could not be reached") from None
        if response.status_code != 200:
            code = {400: "PROVIDER_REQUEST_REJECTED", 401: "PROVIDER_AUTHENTICATION",
                    403: "PROVIDER_ACCESS", 404: "PROVIDER_MODEL_UNAVAILABLE", 429: "PROVIDER_RATE_LIMIT"}.get(
                response.status_code, "PROVIDER_ERROR",
            )
            raise GeminiError(code, "Gemini rejected or could not complete the request")
        try:
            if len(response.content) > 131_072:
                raise ValueError()
            data = response.json()
            if data.get("promptFeedback", {}).get("blockReason"):
                raise GeminiError("MODEL_OUTPUT_BLOCKED", "Gemini did not return a complete review")
            candidate = data["candidates"][0]
            finish = candidate["finishReason"]
            if finish != "STOP":
                code = "MODEL_OUTPUT_TRUNCATED" if finish == "MAX_TOKENS" else "MODEL_OUTPUT_BLOCKED"
                raise GeminiError(code, "Gemini did not return a complete review")
            parts = candidate["content"]["parts"]
            # Do not publish provider thoughts, signatures, or non-text/tool output.
            text = "".join(part["text"] for part in parts if "text" in part and not part.get("thought"))
            if not text or len(text) > 32000:
                raise ValueError()
            usage = data.get("usageMetadata", {})
            metadata = {
                "status": "SUCCESS", "response_id": data.get("responseId"),
                "model": data.get("modelVersion", self.config.model), "finish_reason": finish,
                "usage": {key: usage[key] for key in (
                    "promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount", "totalTokenCount",
                ) if key in usage},
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
            return text, metadata
        except (KeyError, IndexError, TypeError, ValueError):
            raise GeminiError("INVALID_PROVIDER_RESPONSE", "Gemini returned no valid review content") from None

    def close(self):
        self.http.close()
