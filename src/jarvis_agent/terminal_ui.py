"""Small dependency-free terminal presentation helpers."""

from __future__ import annotations

import json
import os
import shutil
import sys
from typing import Any, TextIO


_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[91m"
_GOLD = "\033[93m"
_CYAN = "\033[96m"
_GREEN = "\033[92m"


ARC_TRIANGLE = (
    "             ━━━━━━━━━━━━━━━━━━━━━━━",
    "              ╲                   ╱",
    "               ╲   ━━━━━━━━━━━   ╱",
    "                ╲   ╲       ╱   ╱",
    "                 ╲   ╲     ╱   ╱",
    "                  ╲   ╲   ╱   ╱",
    "                   ╲   ╲ ╱   ╱",
    "                    ╲   ▼   ╱",
    "                     ╲     ╱",
    "                      ╲   ╱",
    "                       ╲ ╱",
    "                        ▼",
)


def _supports_color(stream: TextIO, requested: bool | None) -> bool:
    if requested is False:
        return False
    if os.environ.get("NO_COLOR") is not None or os.environ.get("JARVIS_NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    is_tty = getattr(stream, "isatty", lambda: False)()
    return bool(is_tty) if requested is None else bool(requested and is_tty)


class TerminalUI:
    """Render role-separated output while remaining readable without ANSI support."""

    def __init__(self, *, color: bool | None = None, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdout
        self.color = _supports_color(self.stream, color)

    def paint(self, text: str, *codes: str) -> str:
        if not self.color or not codes:
            return text
        return "".join(codes) + text + _RESET

    def divider(self) -> str:
        width = max(36, min(shutil.get_terminal_size((88, 24)).columns - 2, 96))
        return self.paint("─" * width, _DIM)

    def banner(
        self,
        *,
        version: str,
        workspace: str,
        model: str,
        branch: str | None,
        session_id: str | None,
        approval: str,
        tools: int,
        streaming: bool,
        mode: str,
    ) -> None:
        print(file=self.stream)
        for line in ARC_TRIANGLE:
            print(self.paint(line, _CYAN, _BOLD), file=self.stream)
        print(file=self.stream)
        print(
            "  " + self.paint("J A R V I S", _GOLD, _BOLD) + self.paint(f"   v{version}", _DIM),
            file=self.stream,
        )
        print("  " + self.paint("Local-first Coding Agent", _CYAN), file=self.stream)
        print(self.divider(), file=self.stream)
        print(f"  workspace  {workspace}", file=self.stream)
        print(f"  model      {model}", file=self.stream)
        print(f"  git        {branch or '(not a Git repository)'}", file=self.stream)
        print(f"  session    {session_id or '(not saved)'}", file=self.stream)
        print(
            f"  status     {self.paint('READY', _GREEN, _BOLD)}  ·  "
            f"mode {mode}  ·  tools {tools}  ·  stream {'on' if streaming else 'off'}",
            file=self.stream,
        )
        print(f"  approval   {approval}", file=self.stream)
        print(self.divider(), file=self.stream)
        print("  Enter a coding task, or type /help for commands.", file=self.stream)

    def prompt(self) -> str:
        return "\n" + self.paint("YOU", _GOLD, _BOLD) + "  › "

    def assistant_header(self) -> None:
        print(file=self.stream)
        print(self.paint("JARVIS", _CYAN, _BOLD), file=self.stream)
        print(self.divider(), file=self.stream)

    def assistant_footer(self) -> None:
        print(self.divider(), file=self.stream)

    def thinking(self, turn: int) -> None:
        print(self.paint(f"JARVIS  ◌ thinking · turn {turn}", _CYAN, _DIM), file=sys.stderr)

    def context_trimmed(
        self,
        before: int,
        after: int,
        before_chars: int | None = None,
        after_chars: int | None = None,
    ) -> None:
        detail = f"{before} → {after} messages"
        if before_chars is not None and after_chars is not None:
            detail += f" · {before_chars:,} → {after_chars:,} chars"
        print(
            self.paint(f"CONTEXT  compacted · {detail}", _GOLD),
            file=sys.stderr,
        )

    def verification_required(self) -> None:
        print(
            self.paint("VERIFY   ! executable evidence required after file changes", _GOLD, _BOLD),
            file=sys.stderr,
        )

    def tool_start(self, name: str, arguments: dict[str, Any]) -> None:
        summary = _summarize_arguments(arguments)
        print(
            self.paint("TOOL", _GOLD, _BOLD) + f"    ▶ {name}" + (f"  {summary}" if summary else ""),
            file=sys.stderr,
        )

    def tool_end(self, name: str, ok: bool, content: object, metadata: dict[str, Any]) -> None:
        marker = self.paint("✓", _GREEN, _BOLD) if ok else self.paint("✗", _RED, _BOLD)
        detail = _summarize_result(ok, content, metadata)
        if name == "run_command" and ok and str(content).strip():
            last_line = next(
                (line.strip() for line in reversed(str(content).splitlines()) if line.strip()),
                "",
            )
            if last_line:
                detail = (detail + " · " if detail else "") + last_line[:100]
        print(f"        {marker} {name}" + (f"  {detail}" if detail else ""), file=sys.stderr)

    def answer(self, answer: str) -> None:
        self.assistant_header()
        print(answer, file=self.stream)
        self.assistant_footer()

    def summary(self, payload: dict[str, Any]) -> None:
        completed = payload.get("status") == "completed"
        marker = self.paint("✓", _GREEN, _BOLD) if completed else self.paint("!", _GOLD, _BOLD)
        tokens = payload.get("usage", {}).get("total_tokens", "n/a")
        print(
            f"{marker} {str(payload.get('status', 'unknown')).upper()}  ·  "
            f"{payload.get('stop_reason', 'unknown')}  ·  "
            f"turns {payload.get('turns', 0)}  ·  tools {payload.get('tool_calls', 0)}  ·  "
            f"tokens {tokens}  ·  verify {payload.get('verification_status', 'n/a')}  ·  "
            f"{float(payload.get('elapsed_seconds', 0)):.3f}s",
            file=self.stream,
        )


def _summarize_arguments(arguments: dict[str, Any], *, limit: int = 180) -> str:
    safe: dict[str, Any] = {}
    for name, value in arguments.items():
        if name in {"content", "old_text", "new_text"} and isinstance(value, str):
            safe[name] = f"<{len(value)} chars>"
        elif isinstance(value, str) and len(value) > 100:
            safe[name] = value[:97] + "..."
        else:
            safe[name] = value
    rendered = json.dumps(safe, ensure_ascii=False, separators=(", ", ": "))
    return rendered if len(rendered) <= limit else rendered[: limit - 3] + "..."


def _summarize_result(
    ok: bool,
    content: object,
    metadata: dict[str, Any],
    *,
    limit: int = 180,
) -> str:
    useful = {
        key: value
        for key, value in metadata.items()
        if key in {"path", "file_count", "count", "match_count", "exit_code", "timed_out", "truncated"}
    }
    if useful:
        rendered = " · ".join(f"{key}={value}" for key, value in useful.items())
    elif ok:
        rendered = str(content).replace("\n", " ")[:80]
    else:
        rendered = str(content).replace("\n", " ")
    return rendered if len(rendered) <= limit else rendered[: limit - 3] + "..."
