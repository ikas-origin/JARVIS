"""Bounded local command execution."""

from __future__ import annotations

import os
import re
import subprocess
import sys
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


def _as_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def make_run_command_tool(timeout: float, output_limit: int) -> Tool:
    def run_command(arguments: dict[str, Any], policy: Policy) -> ToolResult:
        command = arguments["command"]
        purpose = arguments["purpose"]
        requested_timeout = float(arguments.get("timeout", timeout))
        requested_timeout = min(max(requested_timeout, 1.0), 300.0)
        policy.check_command(command)
        child_env = _sanitized_environment()
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
            partial = _as_text(error.stdout) + _as_text(error.stderr)
            output, truncated = _truncate(partial, output_limit)
            return ToolResult(
                False,
                output or f"Command timed out after {requested_timeout:g} seconds",
                {"timed_out": True, "truncated": truncated, "purpose": purpose},
            )
        combined = completed.stdout
        if completed.stderr:
            combined += ("\n" if combined else "") + "[stderr]\n" + completed.stderr
        output, truncated = _truncate(combined.rstrip(), output_limit)
        return ToolResult(
            completed.returncode == 0,
            output,
            {"exit_code": completed.returncode, "truncated": truncated, "purpose": purpose},
        )

    return Tool(
        "run_command",
        (
            "Run a local shell command in the workspace. Set purpose='inspect' for discovery and "
            "purpose='verify' only for a test, build, lint, type-check, or other executable validation."
        ),
        {
            "type": "object",
            "properties": {
                "command": {"type": "string", "minLength": 1},
                "purpose": {
                    "type": "string",
                    "enum": ["inspect", "verify"],
                    "description": "inspect gathers information; verify supplies post-change evidence",
                },
                "timeout": {
                    "type": "number",
                    "minimum": 1,
                    "maximum": 300,
                    "description": "Seconds",
                },
            },
            "required": ["command", "purpose"],
            "additionalProperties": False,
        },
        run_command,
    )


_SECRET_ENV_NAME = re.compile(
    r"(?:^|_)(?:API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?|PRIVATE_?KEY)(?:$|_)",
    re.IGNORECASE,
)


def _sanitized_environment() -> dict[str, str]:
    """Keep normal build variables while withholding common credential names."""
    environment = {
        name: value for name, value in os.environ.items() if not _SECRET_ENV_NAME.search(name)
    }
    interpreter_dir = os.path.dirname(os.path.abspath(sys.executable))
    path = environment.get("PATH", "")
    path_entries = path.split(os.pathsep) if path else []
    normalized_entries = {os.path.normcase(os.path.abspath(entry)) for entry in path_entries if entry}
    if os.path.normcase(interpreter_dir) not in normalized_entries:
        environment["PATH"] = (
            interpreter_dir + (os.pathsep + path if path else "")
        )
    return environment
