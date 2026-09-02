"""Minimal OpenAI-compatible Chat Completions client."""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Iterable
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
    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        on_text_delta: Callable[[str], None] | None = None,
    ) -> ModelResponse: ...


def parse_chat_completion(payload: dict[str, Any]) -> ModelResponse:
    if not isinstance(payload, dict):
        raise ModelResponseError("Model response root must be a JSON object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ModelResponseError("Response does not contain choices[0].message")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ModelResponseError("Response does not contain choices[0].message")
    content = message.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise ModelResponseError("Assistant content must be text or null")
    raw_calls = message.get("tool_calls")
    if raw_calls is None:
        raw_calls = []
    if not isinstance(raw_calls, list):
        raise ModelResponseError("Assistant tool_calls must be an array or null")
    calls: list[ToolCall] = []
    call_ids: set[str] = set()
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
            if call_id in call_ids:
                raise ValueError(f"duplicate tool call id: {call_id}")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ModelResponseError(f"Invalid tool call in model response: {exc}") from exc
        call_ids.add(call_id)
        calls.append(ToolCall(call_id, name, arguments))
    if not content.strip() and not calls:
        raise ModelResponseError("Model returned neither text nor tool calls")
    usage = payload.get("usage")
    if usage is None:
        usage = {}
    elif not isinstance(usage, dict):
        raise ModelResponseError("Model usage must be a JSON object or null")
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and not isinstance(finish_reason, str):
        raise ModelResponseError("Model finish_reason must be text or null")
    return ModelResponse(content, calls, finish_reason, usage)


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

    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        on_text_delta: Callable[[str], None] | None = None,
    ) -> ModelResponse:
        streaming = on_text_delta is not None
        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "stream": streaming,
                **({"stream_options": {"include_usage": True}} if streaming else {}),
            },
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
                    if streaming:
                        return parse_chat_completion_stream(response, on_text_delta)
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


def parse_chat_completion_stream(
    lines: Iterable[bytes],
    on_text_delta: Callable[[str], None],
) -> ModelResponse:
    content_parts: list[str] = []
    tool_parts: dict[int, dict[str, str]] = {}
    finish_reason: str | None = None
    usage: dict[str, int] = {}
    saw_done = False
    for raw_line in lines:
        try:
            line = raw_line.decode("utf-8").strip()
        except UnicodeError as exc:
            raise ModelResponseError("Streaming response contains invalid UTF-8") from exc
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            saw_done = True
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ModelResponseError("Streaming response contains invalid JSON") from exc
        if not isinstance(chunk, dict):
            raise ModelResponseError("Streaming event must contain a JSON object")
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        choices = chunk.get("choices") or []
        if not isinstance(choices, list):
            raise ModelResponseError("Streaming choices must be an array")
        if not choices:
            continue
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ModelResponseError("Streaming choice must be a JSON object")
        finish_reason = choice.get("finish_reason") or finish_reason
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            raise ModelResponseError("Streaming delta must be a JSON object")
        text = _stream_fragment(delta.get("content"), "assistant content")
        if text:
            content_parts.append(text)
            on_text_delta(text)
        for raw_call in delta.get("tool_calls") or []:
            if not isinstance(raw_call, dict):
                raise ModelResponseError("Streaming tool call must be a JSON object")
            try:
                index = int(raw_call.get("index", 0))
            except (TypeError, ValueError) as exc:
                raise ModelResponseError("Streaming tool call index must be an integer") from exc
            if index < 0:
                raise ModelResponseError("Streaming tool call index must not be negative")
            part = tool_parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if raw_call.get("id"):
                part["id"] += _stream_fragment(raw_call["id"], "tool call id")
            function = raw_call.get("function") or {}
            if not isinstance(function, dict):
                raise ModelResponseError("Streaming tool function must be a JSON object")
            part["name"] += _stream_fragment(function.get("name"), "tool name")
            part["arguments"] += _stream_fragment(function.get("arguments"), "tool arguments")
    if not saw_done:
        raise ModelResponseError("Streaming response ended without a [DONE] event")
    payload = {
        "choices": [
            {
                "message": {
                    "content": "".join(content_parts),
                    "tool_calls": [
                        {
                            "id": part["id"],
                            "type": "function",
                            "function": {"name": part["name"], "arguments": part["arguments"] or "{}"},
                        }
                        for _, part in sorted(tool_parts.items())
                    ],
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
    }
    return parse_chat_completion(payload)


def _stream_fragment(value: object, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ModelResponseError(f"Streaming {label} fragment must be text or null")
    return value


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
