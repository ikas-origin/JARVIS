"""Bounded local command execution."""

from __future__ import annotations

import os
import subprocess
from typing import Any

from ..policy import Policy
from ..tool_protocol import Tool
from ..types import ToolResult


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    head = limit // 2
    tail = limit - head
    return text[:head] + "\n... output truncated ...\n" + text[-tail:], True


def make_run_command_tool(timeout: float, output_limit: int) -> Tool:
    def run_command(arguments: dict[str, Any], policy: Policy) -> ToolResult:
        command = arguments["command"]
        requested_timeout = float(arguments.get("timeout", timeout))
        requested_timeout = min(max(requested_timeout, 1.0), 300.0)
        policy.check_command(command)
        child_env = os.environ.copy()
        child_env.pop("JARVIS_API_KEY", None)
        try:
            completed = subprocess.run(
                command,
                cwd=policy.workspace,
                env=child_env,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=requested_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            partial = (error.stdout or "") + (error.stderr or "")
            output, truncated = _truncate(partial, output_limit)
            return ToolResult(
                False,
                output or f"Command timed out after {requested_timeout:g} seconds",
                {"timed_out": True, "truncated": truncated},
            )
        combined = completed.stdout
        if completed.stderr:
            combined += ("\n" if combined else "") + "[stderr]\n" + completed.stderr
        output, truncated = _truncate(combined.rstrip(), output_limit)
        return ToolResult(
            completed.returncode == 0,
            output,
            {"exit_code": completed.returncode, "truncated": truncated},
        )

    return Tool(
        "run_command",
        "Run a local shell command in the workspace. Use it for tests, builds, and project inspection.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "number", "description": "Seconds, clamped to 1..300"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        run_command,
    )

