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
        self.write_roots: tuple[Path, ...] | None = None
        self.denied_write_paths: tuple[Path, ...] = ()
        self.commands_allowed = True

    def resolve_path(self, user_path: str) -> Path:
        if not isinstance(user_path, str) or not user_path.strip():
            raise PolicyError("path must be a non-empty string")
        raw = Path(user_path).expanduser()
        candidate = (raw if raw.is_absolute() else self.workspace / raw).resolve(strict=False)
        try:
            candidate.relative_to(self.workspace)
        except ValueError as error:
            raise PolicyError(f"Path escapes workspace: {user_path}") from error
        if _is_sensitive_path(candidate, self.workspace):
            raise PolicyError(f"Access to sensitive path is refused: {user_path}")
        return candidate

    def require_approval(self, action: str) -> None:
        if self.auto_approve:
            return
        if self.confirm is not None and self.confirm(action):
            return
        raise PolicyError(f"Approval denied for: {action}")

    def restrict(
        self,
        *,
        write_roots: tuple[Path, ...] | None,
        commands_allowed: bool,
        denied_write_paths: tuple[Path, ...] = (),
    ) -> None:
        """Temporarily narrow mutating tools for a structured workflow phase."""
        resolved: list[Path] = []
        for root in write_roots or ():
            candidate = root.resolve(strict=False)
            try:
                candidate.relative_to(self.workspace)
            except ValueError as error:
                raise PolicyError(f"Restricted write root escapes workspace: {root}") from error
            resolved.append(candidate)
        denied: list[Path] = []
        for path in denied_write_paths:
            candidate = path.resolve(strict=False)
            try:
                candidate.relative_to(self.workspace)
            except ValueError as error:
                raise PolicyError(f"Denied write path escapes workspace: {path}") from error
            denied.append(candidate)
        self.write_roots = tuple(resolved) if write_roots is not None else None
        self.denied_write_paths = tuple(denied)
        self.commands_allowed = commands_allowed

    def clear_restrictions(self) -> None:
        self.write_roots = None
        self.denied_write_paths = ()
        self.commands_allowed = True

    def check_write_path(self, path: Path) -> None:
        if any(path == denied for denied in self.denied_write_paths):
            raise PolicyError(f"Current workflow phase protects this artifact: {path.name}")
        if self.write_roots is None:
            return
        if any(_is_within(path, root) for root in self.write_roots):
            return
        allowed = ", ".join(str(root.relative_to(self.workspace)) for root in self.write_roots)
        raise PolicyError(f"Current workflow phase only permits writes under: {allowed}")

    def check_command(self, command: str) -> None:
        if not isinstance(command, str) or not command.strip():
            raise PolicyError("command must be a non-empty string")
        if not self.commands_allowed:
            raise PolicyError("Commands are disabled during the current workflow phase")
        if any(pattern.search(command) for pattern in _DANGEROUS_COMMANDS):
            raise PolicyError("Command refused by the dangerous-command policy")
        self.require_approval(f"run command: {command}")


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _is_sensitive_path(candidate: Path, workspace: Path) -> bool:
    parts = tuple(part.lower() for part in candidate.relative_to(workspace).parts)
    if ".git" in parts:
        return True
    name = candidate.name.lower()
    if len(parts) >= 4 and parts[0:2] == (".jarvis", "specs") and name == "state.json":
        return True
    if name == ".env" or name.startswith(".env.") and name != ".env.example":
        return True
    if name in {"id_rsa", "id_ed25519", "credentials", "credentials.json"}:
        return True
    return candidate.suffix.lower() in {".pem", ".p12", ".pfx", ".key"}
