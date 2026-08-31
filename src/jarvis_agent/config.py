"""Runtime configuration loaded from arguments and environment variables."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse

from .errors import ConfigurationError


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_CONFIG_PATH = Path.home() / ".jarvis" / "config.json"


@dataclass(frozen=True, slots=True)
class Config:
    api_key: str | None
    model: str | None
    base_url: str
    workspace: Path
    auth_source: str = "missing"
    config_path: Path = DEFAULT_CONFIG_PATH
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
        config_path: str | Path | None = None,
    ) -> "Config":
        root = Path(workspace or Path.cwd()).expanduser().resolve()
        if not root.is_dir():
            raise ConfigurationError(f"Workspace does not exist or is not a directory: {root}")
        if max_turns < 1:
            raise ConfigurationError("max_turns must be at least 1")
        selected_config_path = Path(
            config_path or os.environ.get("JARVIS_CONFIG") or DEFAULT_CONFIG_PATH
        ).expanduser().resolve(strict=False)
        stored = load_user_config(selected_config_path)
        env_key = os.environ.get("JARVIS_API_KEY") or None
        stored_key = stored.get("api_key") if isinstance(stored.get("api_key"), str) else None
        return cls(
            api_key=env_key or stored_key,
            model=os.environ.get("JARVIS_MODEL") or _optional_string(stored.get("model")),
            base_url=(
                os.environ.get("JARVIS_BASE_URL")
                or _optional_string(stored.get("base_url"))
                or DEFAULT_BASE_URL
            ).rstrip("/"),
            workspace=root,
            auth_source="env" if env_key else "config" if stored_key else "missing",
            config_path=selected_config_path,
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

    @property
    def model_endpoint_is_local(self) -> bool:
        parsed = urlparse(self.base_url)
        return parsed.hostname in {"localhost", "127.0.0.1", "::1"}

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
        issues = list(missing)
        if not transport_secure:
            issues.append("JARVIS_BASE_URL (must be HTTPS unless local)")
        return {
            "ok": not issues,
            "auth": {"available": bool(self.api_key), "source": self.auth_source},
            "model": self.model,
            "base_url": self.base_url,
            "model_endpoint": "local" if self.model_endpoint_is_local else "remote",
            "remote_data_notice": (
                None
                if self.model_endpoint_is_local
                else "Task text, selected workspace files, and command output may be sent to this endpoint."
            ),
            "transport_secure": transport_secure,
            "workspace": str(self.workspace),
            "config_path": str(self.config_path),
            "missing": issues,
        }


def load_user_config(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"Cannot read JARVIS config {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ConfigurationError(f"JARVIS config must contain a JSON object: {path}")
    return payload


def save_user_config(
    *,
    api_key: str,
    model: str,
    base_url: str,
    path: Path = DEFAULT_CONFIG_PATH,
) -> Path:
    if not api_key.strip() or not model.strip():
        raise ConfigurationError("API key and model must not be empty")
    path = path.expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"api_key": api_key.strip(), "model": model.strip(), "base_url": base_url.rstrip("/")}
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix="config-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    except OSError as error:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise ConfigurationError(f"Cannot write JARVIS config {path}: {error}") from error
    return path


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
