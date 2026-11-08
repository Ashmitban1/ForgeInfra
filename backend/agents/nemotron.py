"""NVIDIA-hosted Nemotron client; credentials never enter evidence or tool input."""

from dataclasses import dataclass, field
import math
import os

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL = "nvidia/nemotron-3-ultra-550b-a55b"


class NemotronError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class NemotronConfig:
    api_key: str = field(repr=False)
    model: str = MODEL
    max_rounds: int = 6
    max_tool_calls: int = 8
    request_timeout: float = 90
    budget_seconds: float = 300
    max_tokens: int = 16384
    enable_thinking: bool = True

    @classmethod
    def from_environment(cls):
        key = os.getenv("NVIDIA_API_KEY", "").strip()
        if not key or key in {"NVIDIA_API_KEY", "$NVIDIA_API_KEY", "YOUR_KEY", "YOUR_NVIDIA_API_KEY"}:
            raise NemotronError("NOT_CONFIGURED", "Configure NVIDIA_API_KEY in the backend environment")
        try:
            thinking = os.getenv("NEMOTRON_ENABLE_THINKING", "true").lower()
            if thinking not in {"true", "false"}:
                raise ValueError()
            config = cls(
                api_key=key, model=os.getenv("NEMOTRON_MODEL", MODEL).strip(),
                max_rounds=int(os.getenv("NEMOTRON_MAX_ROUNDS", "6")),
                max_tool_calls=int(os.getenv("NEMOTRON_MAX_TOOL_CALLS", "8")),
                request_timeout=float(os.getenv("NEMOTRON_REQUEST_TIMEOUT_SECONDS", "90")),
                budget_seconds=float(os.getenv("NEMOTRON_BUDGET_SECONDS", "300")),
                max_tokens=int(os.getenv("NEMOTRON_MAX_TOKENS", "16384")),
                enable_thinking=thinking == "true",
            )
            if (not 1 <= config.max_rounds <= 10 or not 3 <= config.max_tool_calls <= 16
                    or not 1 <= config.request_timeout <= 120 or not 5 <= config.budget_seconds <= 600
                    or not 256 <= config.max_tokens <= 16384 or not config.model.strip()
                    or not math.isfinite(config.request_timeout) or not math.isfinite(config.budget_seconds)):
                raise ValueError()
            return config
        except ValueError:
            raise NemotronError("INVALID_CONFIGURATION", "Invalid Nemotron limits/configuration") from None


class NemotronClient:
    def __init__(self, config: NemotronConfig, sdk=None):
        self.config = config
        self.sdk = sdk or OpenAI(
            base_url=BASE_URL, api_key=config.api_key, timeout=config.request_timeout, max_retries=0,
        )

    def complete(self, messages: list[dict], tools: list[dict], remaining_seconds: float):
        try:
            response = self.sdk.chat.completions.create(
                model=self.config.model, messages=messages, tools=tools, tool_choice="auto",
                temperature=1, top_p=0.95, max_tokens=self.config.max_tokens,
                extra_body={"chat_template_kwargs": {
                    "enable_thinking": self.config.enable_thinking, "force_nonempty_content": True,
                }},
                stream=False, timeout=min(self.config.request_timeout, remaining_seconds),
            )
        except APITimeoutError:
            raise NemotronError("PROVIDER_TIMEOUT", "NVIDIA request timed out") from None
        except APIStatusError as error:
            code = {401: "PROVIDER_AUTHENTICATION", 403: "PROVIDER_ACCESS", 429: "PROVIDER_RATE_LIMIT"}.get(
                error.status_code, "PROVIDER_ERROR"
            )
            raise NemotronError(code, "NVIDIA rejected or could not complete the request") from None
        except APIConnectionError:
            raise NemotronError("PROVIDER_UNAVAILABLE", "NVIDIA could not be reached") from None
        if not response.choices:
            raise NemotronError("INVALID_PROVIDER_RESPONSE", "NVIDIA returned no completion choices")
        return response

    def close(self):
        self.sdk.close()
