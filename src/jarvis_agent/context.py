"""Conversation normalization and deterministic context trimming."""

from __future__ import annotations

from copy import deepcopy
import json

from .errors import AgentLimitError
from .types import Message


def _size(messages: list[Message]) -> int:
    return len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")))


def _groups(messages: list[Message]) -> list[list[Message]]:
    """Keep assistant tool calls adjacent to all of their tool results."""
    groups: list[list[Message]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        group = [message]
        if message.get("role") == "assistant" and message.get("tool_calls"):
            index += 1
            while index < len(messages) and messages[index].get("role") == "tool":
                group.append(messages[index])
                index += 1
            groups.append(group)
            continue
        groups.append(group)
        index += 1
    return groups


def trim_messages(
    messages: list[Message],
    *,
    max_chars: int,
    per_tool_chars: int = 8_000,
) -> list[Message]:
    """Fit history without splitting tool-call trajectories.

    System messages and every user message are retained. Old tool trajectories
    are removed first. Oversized tool outputs are deterministically shortened.
    """
    normalized = deepcopy(messages)
    for message in normalized:
        if message.get("role") == "tool" and len(message.get("content", "")) > per_tool_chars:
            content = message["content"]
            half = per_tool_chars // 2
            message["content"] = (
                content[:half]
                + "\n...[older tool output truncated by JARVIS]...\n"
                + content[-half:]
            )
    if _size(normalized) <= max_chars:
        return normalized

    protected: list[Message] = [
        message for message in normalized if message.get("role") in {"system", "user"}
    ]
    removable = [
        group
        for group in _groups(normalized)
        if not all(message.get("role") in {"system", "user"} for message in group)
    ]
    kept = list(removable)
    while kept:
        candidate_parts = [*protected, *(message for group in kept for message in group)]
        # Re-sort into original order by object identity to preserve dialogue sequence.
        positions = {id(message): index for index, message in enumerate(normalized)}
        candidate_parts.sort(key=lambda message: positions[id(message)])
        if _size(candidate_parts) <= max_chars:
            return candidate_parts
        kept.pop(0)

    if _size(protected) <= max_chars:
        return protected
    raise AgentLimitError(
        "System and user messages alone exceed the context budget; shorten the task or raise the limit"
    )

