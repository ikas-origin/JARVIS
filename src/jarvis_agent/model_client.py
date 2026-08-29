"""Minimal OpenAI-compatible Chat Completions client."""

from __future__ import annotations

import json
import random
import time
from typing import Any, Protocol
from urllib import error, request

from .errors import (
    ModelAuthenticationError,
    ModelError,
    ModelRateLimitError,
    ModelResponseError,
)
from .types import Message, ModelResponse, ToolCall


class ModelClient(Protocol):
    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> ModelResponse: ...


def parse_chat_completion(payload: dict[str, Any]) -> ModelResponse:
    try:
        choice = payload["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelResponseError("Response does not contain choices[0].message") from exc
    content = message.get("content") or ""
    raw_calls = message.get("tool_calls") or []
    calls: list[ToolCall] = []
    for raw in raw_calls:
        try:
            call_id = raw["id"]
            function = raw["function"]
            name = function["name"]
            raw_arguments = function.get("arguments", "{}")
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            if not isinstance(call_id, str) or not call_id:
                raise ValueError("missing tool call id")
            if not isinstance(name, str) or not name:
                raise ValueError("missing tool name")
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments are not an object")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ModelResponseError(f"Invalid tool call in model response: {exc}") from exc
        calls.append(ToolCall(call_id, name, arguments))
    if not isinstance(content, str):
        raise ModelResponseError("Assistant content must be text or null")
    if not content.strip() and not calls:
        raise ModelResponseError("Model returned neither text nor tool calls")
    usage = payload.get("usage") or {}
    return ModelResponse(content, calls, choice.get("finish_reason"), usage)


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout: float = 90.0,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.timeout = timeout
        self.max_retries = max_retries

    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> ModelResponse:
        body = json.dumps(
            {"model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto"},
            ensure_ascii=False,
        ).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            http_request = request.Request(
                self.url,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json; charset=utf-8",
                    "User-Agent": "JARVIS-Coding-Agent/0.1",
                },
            )
            try:
                with request.urlopen(http_request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ModelResponseError("Model response root must be a JSON object")
                return parse_chat_completion(payload)
            except error.HTTPError as exc:
                if exc.code in {401, 403}:
                    raise ModelAuthenticationError("Model API authentication failed") from exc
                if exc.code == 429:
                    last_error = ModelRateLimitError("Model API rate limit exceeded")
                elif 500 <= exc.code < 600:
                    last_error = ModelError(f"Model API server error: HTTP {exc.code}")
                else:
                    detail = _safe_error_detail(exc, self.api_key)
                    raise ModelError(f"Model API rejected the request: HTTP {exc.code}{detail}") from exc
            except (error.URLError, TimeoutError) as exc:
                last_error = ModelError(f"Model API network error: {exc.reason if hasattr(exc, 'reason') else exc}")
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ModelResponseError("Model API returned invalid JSON") from exc
            if attempt < self.max_retries:
                time.sleep((2**attempt) + random.uniform(0, 0.25))
        assert last_error is not None
        raise last_error


def _safe_error_detail(exc: error.HTTPError, api_key: str) -> str:
    try:
        payload = json.loads(exc.read(4096).decode("utf-8", errors="replace"))
        message = payload.get("error", {}).get("message", "")
        if isinstance(message, str) and message:
            redacted = message.replace(api_key, "[REDACTED]") if api_key else message
            return ": " + redacted[:500]
    except (AttributeError, json.JSONDecodeError, OSError):
        pass
    return ""
