"""The provider-independent Coding Agent loop."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import platform
import time
from typing import Any

from .config import Config
from .context import trim_messages
from .model_client import ModelClient
from .project_context import load_project_context
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
    usage: dict[str, int]
    elapsed_seconds: float
    tool_usage: dict[str, int]
    verification_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.status == "completed",
            "status": self.status,
            "answer": self.answer,
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "stop_reason": self.stop_reason,
            "usage": self.usage,
            "elapsed_seconds": self.elapsed_seconds,
            "tool_usage": self.tool_usage,
            "verification_status": self.verification_status,
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
        stream: bool = False,
    ) -> None:
        self.config = config
        self.client = client
        self.tools = tools
        self.on_event = on_event or (lambda _name, _data: None)
        self.checkpoint = checkpoint or (lambda _messages: None)
        self.stream = stream
        self.messages: list[Message] = initial_messages or [self._new_system_message()]
        self._checkpoint()

    def reset_context(self) -> None:
        """Start a fresh conversation while preserving the runtime system prompt."""
        system_message = next(
            (message for message in self.messages if message.get("role") == "system"),
            None,
        )
        if system_message is None:
            system_message = self._new_system_message()
        self.messages = [dict(system_message)]
        self._checkpoint()

    def run(self, task: str) -> AgentResult:
        started = time.monotonic()
        usage: dict[str, int] = {}
        tool_usage: dict[str, int] = {}
        verification_status = "not_required"

        def finish(
            status: str, answer: str, turns: int, tool_calls: int, stop_reason: str
        ) -> AgentResult:
            return AgentResult(
                status,
                answer,
                turns,
                tool_calls,
                stop_reason,
                dict(usage),
                round(time.monotonic() - started, 3),
                dict(tool_usage),
                verification_status,
            )

        if not task.strip():
            return finish("failed", "Task must not be empty", 0, 0, "invalid_task")
        self.messages.append({"role": "user", "content": task.strip()})
        self._checkpoint()
        tool_call_count = 0
        repeated_error: tuple[str, int] | None = None
        needs_verification = False

        for turn in range(1, self.config.max_turns + 1):
            self.on_event("model_request", {"turn": turn})
            request_messages = trim_messages(
                self.messages,
                max_chars=self.config.max_context_chars,
                per_tool_chars=min(8_000, self.config.max_tool_output_chars),
            )
            response = self.client.complete(
                request_messages,
                self.tools.schemas,
                (
                    lambda delta: self.on_event("assistant_delta", {"text": delta})
                    if self.stream
                    else None
                ),
            )
            for name, value in response.usage.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    usage[name] = usage.get(name, 0) + value
            self.messages.append(_assistant_message(response))
            self._checkpoint()
            if response.content.strip():
                self.on_event("assistant_text", {"text": response.content})
            if not response.tool_calls:
                if needs_verification and self.tools.policy.commands_allowed:
                    self.messages.append(
                        {
                            "role": "user",
                            "content": (
                                "JARVIS verification gate: files were changed after the last successful "
                                "command. Run the most relevant tests, build, lint, or other executable "
                                "check now. If it fails, fix the problem and rerun it before answering."
                            ),
                        }
                    )
                    self._checkpoint()
                    self.on_event("verification_required", {"turn": turn})
                    continue
                return finish(
                    "completed", response.content.strip(), turn, tool_call_count, "model_final_answer"
                )

            for call in response.tool_calls:
                if tool_call_count >= self.config.max_tool_calls:
                    return finish(
                        "stopped",
                        "Stopped before executing more tools because the tool-call limit was reached.",
                        turn,
                        tool_call_count,
                        "max_tool_calls",
                    )
                tool_call_count += 1
                tool_usage[call.name] = tool_usage.get(call.name, 0) + 1
                self.on_event("tool_start", {"name": call.name, "arguments": call.arguments})
                result = self.tools.execute(call.name, call.arguments)
                if result.ok and call.name in {"write_file", "edit_file"}:
                    path = str(result.metadata.get("path", "")).replace("\\", "/")
                    if not path.startswith(".jarvis/"):
                        needs_verification = True
                        verification_status = "required"
                elif result.ok and call.name == "run_command":
                    if needs_verification:
                        verification_status = "passed"
                    needs_verification = False
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
                        return finish(
                            "stopped",
                            "Stopped after the same tool error occurred three times.",
                            turn,
                            tool_call_count,
                            "repeated_tool_error",
                        )

        return finish(
            "stopped",
            f"Stopped after reaching the maximum of {self.config.max_turns} model turns.",
            self.config.max_turns,
            tool_call_count,
            "max_turns",
        )

    def _checkpoint(self) -> None:
        self.checkpoint(self.messages)

    def _new_system_message(self) -> Message:
        content = (
            SYSTEM_PROMPT
            + f"\nRuntime: {platform.system()} {platform.release()}; workspace: {self.config.workspace}"
        )
        project_context = load_project_context(self.config.workspace)
        if project_context is not None:
            content += project_context.prompt_section(self.config.workspace)
        return {"role": "system", "content": content}


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
