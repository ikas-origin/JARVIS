"""The provider-independent Coding Agent loop."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import platform
from typing import Any

from .config import Config
from .context import trim_messages
from .model_client import ModelClient
from .prompts import SYSTEM_PROMPT
from .tool_protocol import ToolRegistry
from .types import Message, ModelResponse, ToolCall


EventCallback = Callable[[str, dict[str, Any]], None]
CheckpointCallback = Callable[[list[Message]], None]


@dataclass(frozen=True, slots=True)
class AgentResult:
    status: str
    answer: str
    turns: int
    tool_calls: int
    stop_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.status == "completed",
            "status": self.status,
            "answer": self.answer,
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "stop_reason": self.stop_reason,
        }


class Agent:
    def __init__(
        self,
        config: Config,
        client: ModelClient,
        tools: ToolRegistry,
        *,
        on_event: EventCallback | None = None,
        initial_messages: list[Message] | None = None,
        checkpoint: CheckpointCallback | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.tools = tools
        self.on_event = on_event or (lambda _name, _data: None)
        self.checkpoint = checkpoint or (lambda _messages: None)
        self.messages: list[Message] = initial_messages or [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
                + f"\nRuntime: {platform.system()} {platform.release()}; workspace: {config.workspace}",
            }
        ]
        self._checkpoint()

    def run(self, task: str) -> AgentResult:
        if not task.strip():
            return AgentResult("failed", "Task must not be empty", 0, 0, "invalid_task")
        self.messages.append({"role": "user", "content": task.strip()})
        self._checkpoint()
        tool_call_count = 0
        repeated_error: tuple[str, int] | None = None

        for turn in range(1, self.config.max_turns + 1):
            self.on_event("model_request", {"turn": turn})
            request_messages = trim_messages(
                self.messages,
                max_chars=self.config.max_context_chars,
                per_tool_chars=min(8_000, self.config.max_tool_output_chars),
            )
            response = self.client.complete(request_messages, self.tools.schemas)
            self.messages.append(_assistant_message(response))
            self._checkpoint()
            if response.content.strip():
                self.on_event("assistant_text", {"text": response.content})
            if not response.tool_calls:
                return AgentResult(
                    "completed", response.content.strip(), turn, tool_call_count, "model_final_answer"
                )

            for call in response.tool_calls:
                if tool_call_count >= self.config.max_tool_calls:
                    return AgentResult(
                        "stopped",
                        "Stopped before executing more tools because the tool-call limit was reached.",
                        turn,
                        tool_call_count,
                        "max_tool_calls",
                    )
                tool_call_count += 1
                self.on_event("tool_start", {"name": call.name, "arguments": call.arguments})
                result = self.tools.execute(call.name, call.arguments)
                payload = json.dumps(result.to_payload(), ensure_ascii=False)
                if len(payload) > self.config.max_tool_output_chars:
                    payload = _truncate(payload, self.config.max_tool_output_chars)
                self.messages.append(
                    {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": payload}
                )
                self._checkpoint()
                self.on_event("tool_end", {"name": call.name, "ok": result.ok, "content": result.content})
                if result.ok:
                    repeated_error = None
                else:
                    signature = f"{call.name}:{result.metadata.get('error_type')}:{result.content}"
                    repeated_error = (
                        (signature, repeated_error[1] + 1)
                        if repeated_error and repeated_error[0] == signature
                        else (signature, 1)
                    )
                    if repeated_error[1] >= 3:
                        return AgentResult(
                            "stopped",
                            "Stopped after the same tool error occurred three times.",
                            turn,
                            tool_call_count,
                            "repeated_tool_error",
                        )

        return AgentResult(
            "stopped",
            f"Stopped after reaching the maximum of {self.config.max_turns} model turns.",
            self.config.max_turns,
            tool_call_count,
            "max_turns",
        )

    def _checkpoint(self) -> None:
        self.checkpoint(self.messages)


def _assistant_message(response: ModelResponse) -> Message:
    message: Message = {"role": "assistant", "content": response.content or None}
    if response.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)},
            }
            for call in response.tool_calls
        ]
    return message


def _truncate(value: str, limit: int) -> str:
    half = limit // 2
    return value[:half] + "\n...[tool result truncated]...\n" + value[-half:]
