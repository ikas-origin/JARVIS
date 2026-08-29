"""Runtime configuration loaded from arguments and environment variables."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse

from .errors import ConfigurationError


DEFAULT_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True, slots=True)
class Config:
    api_key: str | None
    model: str | None
    base_url: str
    workspace: Path
    max_turns: int = 20
    max_tool_calls: int = 50
    request_timeout: float = 90.0
    command_timeout: float = 60.0
    max_context_chars: int = 120_000
    max_tool_output_chars: int = 20_000

    @classmethod
    def from_env(
        cls,
        *,
        workspace: str | Path | None = None,
        max_turns: int = 20,
    ) -> "Config":
        root = Path(workspace or Path.cwd()).expanduser().resolve()
        if not root.is_dir():
            raise ConfigurationError(f"Workspace does not exist or is not a directory: {root}")
        if max_turns < 1:
            raise ConfigurationError("max_turns must be at least 1")
        return cls(
            api_key=os.environ.get("JARVIS_API_KEY") or None,
            model=os.environ.get("JARVIS_MODEL") or None,
            base_url=(os.environ.get("JARVIS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            workspace=root,
            max_turns=max_turns,
        )

    def validate_for_run(self) -> None:
        missing: list[str] = []
        if not self.api_key:
            missing.append("JARVIS_API_KEY")
        if not self.model:
            missing.append("JARVIS_MODEL")
        if missing:
            raise ConfigurationError(
                "Missing required environment variable(s): " + ", ".join(missing)
            )
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ConfigurationError("JARVIS_BASE_URL must be an absolute HTTP(S) URL")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ConfigurationError(
                "JARVIS_BASE_URL must use HTTPS unless it points to a local model server"
            )

    def doctor(self) -> dict[str, object]:
        missing = [
            name
            for name, value in (
                ("JARVIS_API_KEY", self.api_key),
                ("JARVIS_MODEL", self.model),
            )
            if not value
        ]
        parsed = urlparse(self.base_url)
        transport_secure = parsed.scheme == "https" or (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        )
        return {
            "ok": not missing,
            "auth": {"available": bool(self.api_key), "source": "env" if self.api_key else "missing"},
            "model": self.model,
            "base_url": self.base_url,
            "transport_secure": transport_secure,
            "workspace": str(self.workspace),
            "missing": missing,
        }
