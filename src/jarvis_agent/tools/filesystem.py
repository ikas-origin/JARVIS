"""Workspace-confined file tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import ToolError
from ..policy import Policy
from ..tool_protocol import Tool
from ..types import ToolResult


def _relative(path: Path, policy: Policy) -> str:
    value = str(path.relative_to(policy.workspace))
    return value or "."


def read_file(arguments: dict[str, Any], policy: Policy) -> ToolResult:
    path = policy.resolve_path(arguments["path"])
    if not path.is_file():
        raise ToolError(f"File does not exist: {arguments['path']}")
    offset = arguments.get("offset", 1)
    limit = arguments.get("limit", 400)
    if offset < 1 or limit < 1 or limit > 2000:
        raise ToolError("offset must be >= 1 and limit must be between 1 and 2000")
    lines = path.read_text(encoding="utf-8").splitlines()
    selected = lines[offset - 1 : offset - 1 + limit]
    numbered = "\n".join(f"{number:>6} | {line}" for number, line in enumerate(selected, offset))
    return ToolResult(
        True,
        numbered,
        {"path": _relative(path, policy), "line_count": len(lines), "returned_lines": len(selected)},
    )


def list_files(arguments: dict[str, Any], policy: Policy) -> ToolResult:
    root = policy.resolve_path(arguments.get("path", "."))
    if not root.is_dir():
        raise ToolError(f"Directory does not exist: {arguments.get('path', '.')}")
    limit = arguments.get("limit", 200)
    if limit < 1 or limit > 2000:
        raise ToolError("limit must be between 1 and 2000")
    ignored = {".git", ".venv", "__pycache__", "node_modules"}
    files: list[str] = []
    truncated = False
    for path in sorted(root.rglob("*")):
        if any(part in ignored for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            if len(files) >= limit:
                truncated = True
                break
            files.append(_relative(path, policy))
    return ToolResult(True, "\n".join(files), {"count": len(files), "truncated": truncated})


def write_file(arguments: dict[str, Any], policy: Policy) -> ToolResult:
    path = policy.resolve_path(arguments["path"])
    policy.require_approval(f"write file: {_relative(path, policy)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = arguments["content"]
    path.write_text(content, encoding="utf-8", newline="")
    return ToolResult(True, f"Wrote {len(content)} characters", {"path": _relative(path, policy)})


def edit_file(arguments: dict[str, Any], policy: Policy) -> ToolResult:
    path = policy.resolve_path(arguments["path"])
    if not path.is_file():
        raise ToolError(f"File does not exist: {arguments['path']}")
    old_text = arguments["old_text"]
    new_text = arguments["new_text"]
    if not old_text:
        raise ToolError("old_text must not be empty")
    original = path.read_text(encoding="utf-8")
    matches = original.count(old_text)
    if matches != 1:
        raise ToolError(f"old_text must match exactly once; found {matches} matches")
    policy.require_approval(f"edit file: {_relative(path, policy)}")
    path.write_text(original.replace(old_text, new_text, 1), encoding="utf-8", newline="")
    return ToolResult(True, "Replaced one exact match", {"path": _relative(path, policy)})


_NO_EXTRA = {"additionalProperties": False}

FILESYSTEM_TOOLS = [
    Tool(
        "list_files",
        "List files recursively under a workspace directory. Use this to discover the project structure.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative directory; defaults to ."},
                "limit": {"type": "integer", "description": "Maximum files to return; defaults to 200"},
            },
            **_NO_EXTRA,
        },
        list_files,
    ),
    Tool(
        "read_file",
        "Read a UTF-8 text file with line numbers. Read before editing.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "description": "First line, 1-based"},
                "limit": {"type": "integer", "description": "Maximum lines, up to 2000"},
            },
            "required": ["path"],
            **_NO_EXTRA,
        },
        read_file,
    ),
    Tool(
        "write_file",
        "Create or fully overwrite a UTF-8 text file inside the workspace.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
            **_NO_EXTRA,
        },
        write_file,
    ),
    Tool(
        "edit_file",
        "Replace one exact, unique text occurrence in an existing UTF-8 file.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
            **_NO_EXTRA,
        },
        edit_file,
    ),
]

