"""Durable, workspace-bound conversation sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any
from uuid import uuid4

from .errors import ConfigurationError
from .types import Message


SESSION_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Session:
    id: str
    workspace: Path
    created_at: str
    updated_at: str
    messages: list[Message]

    def summary(self) -> dict[str, Any]:
        user_messages = [message for message in self.messages if message.get("role") == "user"]
        last_task = str(user_messages[-1].get("content", ""))[:120] if user_messages else ""
        return {
            "id": self.id,
            "workspace": str(self.workspace),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.messages),
            "last_task": last_task,
        }


class SessionStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.expanduser().resolve(strict=False)

    def create(self, workspace: Path) -> Session:
        timestamp = _now()
        return Session(uuid4().hex, workspace.resolve(), timestamp, timestamp, [])

    def save(self, session: Session) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        session.updated_at = _now()
        payload = {
            "version": SESSION_VERSION,
            "id": session.id,
            "workspace": str(session.workspace),
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "messages": session.messages,
        }
        path = self._path(session.id)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.directory,
                prefix=f"{session.id}-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                json.dump(payload, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, path)
        except (OSError, TypeError) as error:
            if temporary_name:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    pass
            raise ConfigurationError(f"Cannot save JARVIS session {session.id}: {error}") from error

    def load(self, session_id: str, *, workspace: Path | None = None) -> Session:
        if not session_id or any(character not in "0123456789abcdef" for character in session_id.lower()):
            raise ConfigurationError("Session ID must contain only hexadecimal characters")
        path = self._path(session_id)
        if not path.is_file():
            raise ConfigurationError(f"Session not found: {session_id}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            session = _parse_session(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError, ValueError) as error:
            raise ConfigurationError(f"Cannot load JARVIS session {session_id}: {error}") from error
        if workspace is not None and session.workspace != workspace.resolve():
            raise ConfigurationError(
                f"Session {session_id} belongs to {session.workspace}, not {workspace.resolve()}"
            )
        return session

    def latest(self, workspace: Path) -> Session | None:
        target = workspace.resolve()
        matches = [session for session in self.list() if session.workspace == target]
        return max(matches, key=lambda session: session.updated_at, default=None)

    def list(self) -> list[Session]:
        if not self.directory.is_dir():
            return []
        sessions: list[Session] = []
        for path in self.directory.glob("*.json"):
            try:
                sessions.append(_parse_session(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError, ValueError):
                continue
        return sorted(sessions, key=lambda session: session.updated_at, reverse=True)

    def _path(self, session_id: str) -> Path:
        return self.directory / f"{session_id}.json"


def _parse_session(payload: object) -> Session:
    if not isinstance(payload, dict) or payload.get("version") != SESSION_VERSION:
        raise ValueError("unsupported session format")
    session_id = payload["id"]
    messages = payload["messages"]
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("invalid session id")
    if not isinstance(messages, list) or not all(isinstance(message, dict) for message in messages):
        raise ValueError("invalid session messages")
    allowed_roles = {"system", "user", "assistant", "tool"}
    if any(message.get("role") not in allowed_roles for message in messages):
        raise ValueError("invalid message role")
    return Session(
        id=session_id,
        workspace=Path(payload["workspace"]).resolve(),
        created_at=str(payload["created_at"]),
        updated_at=str(payload["updated_at"]),
        messages=messages,
    )

