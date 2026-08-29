"""Workspace and execution policy shared by local tools."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import re

from .errors import PolicyError


ConfirmCallback = Callable[[str], bool]


_DANGEROUS_COMMANDS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(^|[;&|]\s*)rm\s+(-[^\s]*r[^\s]*f|-[^\s]*f[^\s]*r)\b",
        r"\bgit\s+(reset\s+--hard|clean\s+-[^\s]*f)",
        r"\b(del|erase|rmdir)\s+(/s|/q)",
        r"\bRemove-Item\b[^\r\n]*(?:-Recurse|-Force)",
        r"\b(format|mkfs(?:\.[a-z0-9]+)?|diskpart)\b",
        r"\b(shutdown|reboot|Restart-Computer|Stop-Computer)\b",
        r"(?:^|\s)(?:/|[A-Za-z]:\\)(?:\s|$).*(?:rm|Remove-Item|del)",
    )
)


class Policy:
    def __init__(
        self,
        workspace: Path,
        *,
        auto_approve: bool = False,
        confirm: ConfirmCallback | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.auto_approve = auto_approve
        self.confirm = confirm

    def resolve_path(self, user_path: str) -> Path:
        if not isinstance(user_path, str) or not user_path.strip():
            raise PolicyError("path must be a non-empty string")
        raw = Path(user_path).expanduser()
        candidate = (raw if raw.is_absolute() else self.workspace / raw).resolve(strict=False)
        try:
            candidate.relative_to(self.workspace)
        except ValueError as error:
            raise PolicyError(f"Path escapes workspace: {user_path}") from error
        return candidate

    def require_approval(self, action: str) -> None:
        if self.auto_approve:
            return
        if self.confirm is not None and self.confirm(action):
            return
        raise PolicyError(f"Approval denied for: {action}")

    def check_command(self, command: str) -> None:
        if not isinstance(command, str) or not command.strip():
            raise PolicyError("command must be a non-empty string")
        if any(pattern.search(command) for pattern in _DANGEROUS_COMMANDS):
            raise PolicyError("Command refused by the dangerous-command policy")
        self.require_approval(f"run command: {command}")

