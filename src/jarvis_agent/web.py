"""Local-only Web console for the JARVIS Coding Agent."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import traceback
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from uuid import uuid4
import webbrowser

from . import __version__
from .agent import Agent
from .config import Config
from .errors import JarvisError
from .model_client import ModelClient, OpenAICompatibleClient
from .policy import Policy
from .session import Session, SessionStore
from .tool_protocol import ToolRegistry
from .tools import built_in_tools


_STATIC_ROOT = Path(__file__).with_name("web_static")
_MAX_REQUEST_BYTES = 64 * 1024
_MAX_TASK_CHARS = 20_000
_APPROVAL_TIMEOUT_SECONDS = 300.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WebBusyError(JarvisError):
    code = "agent_busy"


class WebNotFoundError(JarvisError):
    code = "not_found"


@dataclass(slots=True)
class PendingApproval:
    id: str
    task_id: str
    action: str
    resolved: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


@dataclass(slots=True)
class WebTask:
    id: str
    prompt: str
    status: str = "queued"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: dict[str, str] | None = None


class WebRuntime:
    """Own one Agent and serialize all mutations of its workspace and history."""

    def __init__(
        self,
        config: Config,
        *,
        auto_approve: bool = False,
        save_session: bool = True,
        client: ModelClient | None = None,
    ) -> None:
        self.config = config
        self.auto_approve = auto_approve
        self._lock = threading.RLock()
        self._tasks: dict[str, WebTask] = {}
        self._task_order: list[str] = []
        self._active_task_id: str | None = None
        self._approvals: dict[str, PendingApproval] = {}
        self._worker: threading.Thread | None = None

        self.session_store = SessionStore(config.config_path.parent / "sessions")
        self.session: Session | None = (
            self.session_store.create(config.workspace) if save_session else None
        )

        def checkpoint(messages: list[dict[str, Any]]) -> None:
            if self.session is not None:
                self.session.messages = messages
                self.session_store.save(self.session)

        policy = Policy(
            config.workspace,
            auto_approve=auto_approve,
            confirm=None if auto_approve else self._request_approval,
        )
        registry = ToolRegistry(
            built_in_tools(
                command_timeout=config.command_timeout,
                output_limit=config.max_tool_output_chars,
            ),
            policy,
        )
        selected_client = client or OpenAICompatibleClient(
            api_key=config.api_key or "",
            model=config.model or "",
            base_url=config.base_url,
            timeout=config.request_timeout,
        )
        self.agent = Agent(
            config,
            selected_client,
            registry,
            on_event=self._record_agent_event,
            checkpoint=checkpoint if self.session is not None else None,
            stream=True,
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            active = self._tasks.get(self._active_task_id or "")
            return {
                "ok": True,
                "version": __version__,
                "workspace": str(self.config.workspace),
                "model": self.config.model,
                "endpoint": "local" if self.config.model_endpoint_is_local else "remote",
                "approval": "automatic" if self.auto_approve else "ask in browser",
                "tool_count": len(self.agent.tools.schemas),
                "session_id": self.session.id if self.session else None,
                "active_task_id": active.id if active and active.status in _ACTIVE_STATUSES else None,
                "active_status": active.status if active and active.status in _ACTIVE_STATUSES else None,
            }

    def start_task(self, prompt: str) -> dict[str, Any]:
        normalized = prompt.strip() if isinstance(prompt, str) else ""
        if not normalized:
            raise JarvisError("Task must not be empty")
        if len(normalized) > _MAX_TASK_CHARS:
            raise JarvisError(f"Task must not exceed {_MAX_TASK_CHARS} characters")
        with self._lock:
            active = self._tasks.get(self._active_task_id or "")
            if active is not None and active.status in _ACTIVE_STATUSES:
                raise WebBusyError(
                    "JARVIS is already running a task for this workspace; wait for it to finish"
                )
            task = WebTask(uuid4().hex, normalized)
            self._tasks[task.id] = task
            self._task_order.append(task.id)
            stale_ids = self._task_order[:-20]
            self._task_order = self._task_order[-20:]
            for stale_id in stale_ids:
                self._tasks.pop(stale_id, None)
            self._active_task_id = task.id
            self._worker = threading.Thread(
                target=self._run_task,
                args=(task.id,),
                name=f"jarvis-web-{task.id[:8]}",
                daemon=True,
            )
            self._worker.start()
            return {"ok": True, "task_id": task.id, "status": task.status}

    def task_snapshot(self, task_id: str, *, after: int = 0) -> dict[str, Any]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise WebNotFoundError(f"Unknown Web task: {task_id}")
            events = [dict(event) for event in task.events if int(event["seq"]) > after]
            return {
                "ok": True,
                "task": {
                    "id": task.id,
                    "prompt": task.prompt,
                    "status": task.status,
                    "created_at": task.created_at,
                    "updated_at": task.updated_at,
                    "events": events,
                    "last_seq": len(task.events),
                    "result": dict(task.result) if task.result else None,
                    "error": dict(task.error) if task.error else None,
                },
            }

    def resolve_approval(self, approval_id: str, approved: bool) -> dict[str, Any]:
        if not isinstance(approved, bool):
            raise JarvisError("approved must be a boolean")
        with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None or approval.resolved.is_set():
                raise WebNotFoundError(f"Unknown or resolved approval: {approval_id}")
            approval.approved = approved
            approval.resolved.set()
            return {"ok": True, "approval_id": approval_id, "approved": approved}

    def _run_task(self, task_id: str) -> None:
        with self._lock:
            task = self._tasks[task_id]
            task.status = "running"
            task.updated_at = _now()
            self._append_event(task, "task_started", {"task": task.prompt})
        try:
            result = self.agent.run(task.prompt).to_dict()
            with self._lock:
                task.result = result
                task.status = str(result["status"])
                task.updated_at = _now()
                self._append_event(task, "task_finished", result)
        except JarvisError as error:
            with self._lock:
                task.status = "failed"
                task.error = {"type": error.code, "message": str(error)}
                task.updated_at = _now()
                self._append_event(task, "task_failed", task.error)
        except Exception:
            traceback.print_exc()
            with self._lock:
                task.status = "failed"
                task.error = {
                    "type": "internal_error",
                    "message": "Unexpected Web worker failure; inspect the local terminal",
                }
                task.updated_at = _now()
                self._append_event(task, "task_failed", task.error)
        finally:
            with self._lock:
                for approval in self._approvals.values():
                    if approval.task_id == task_id and not approval.resolved.is_set():
                        approval.resolved.set()

    def _record_agent_event(self, name: str, data: dict[str, Any]) -> None:
        with self._lock:
            task = self._tasks.get(self._active_task_id or "")
            if task is None:
                return
            if name == "assistant_text":
                return
            safe_data = _safe_event_data(name, data)
            self._append_event(task, name, safe_data)

    def _request_approval(self, action: str) -> bool:
        with self._lock:
            task = self._tasks.get(self._active_task_id or "")
            if task is None:
                return False
            approval = PendingApproval(uuid4().hex, task.id, action)
            self._approvals[approval.id] = approval
            task.status = "waiting_approval"
            task.updated_at = _now()
            self._append_event(
                task,
                "approval_required",
                {"approval_id": approval.id, "action": action},
            )
        resolved = approval.resolved.wait(_APPROVAL_TIMEOUT_SECONDS)
        with self._lock:
            self._approvals.pop(approval.id, None)
            if task.status == "waiting_approval":
                task.status = "running"
            task.updated_at = _now()
            approved = resolved and approval.approved
            self._append_event(
                task,
                "approval_resolved",
                {"approval_id": approval.id, "approved": approved},
            )
            return approved

    @staticmethod
    def _append_event(task: WebTask, name: str, data: dict[str, Any]) -> None:
        task.events.append(
            {"seq": len(task.events) + 1, "type": name, "at": _now(), "data": data}
        )
        task.updated_at = _now()


_ACTIVE_STATUSES = {"queued", "running", "waiting_approval"}


def _safe_event_data(name: str, data: dict[str, Any]) -> dict[str, Any]:
    if name == "assistant_delta":
        return {"text": str(data.get("text", ""))}
    if name == "tool_start":
        arguments = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
        safe_arguments: dict[str, Any] = {}
        for key, value in arguments.items():
            if key in {"content", "old_text", "new_text"} and isinstance(value, str):
                safe_arguments[key] = f"<{len(value)} chars>"
            elif isinstance(value, str) and len(value) > 300:
                safe_arguments[key] = value[:297] + "..."
            else:
                safe_arguments[key] = value
        return {"name": str(data.get("name", "")), "arguments": safe_arguments}
    if name == "tool_end":
        content = str(data.get("content", ""))
        if len(content) > 2_000:
            content = content[:1_000] + "\n...[Web output truncated]...\n" + content[-1_000:]
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        return {
            "name": str(data.get("name", "")),
            "ok": bool(data.get("ok")),
            "content": content,
            "metadata": metadata,
        }
    return json.loads(json.dumps(data, ensure_ascii=False, default=str))


class JarvisWebServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        runtime: WebRuntime,
        token: str,
        static_root: Path = _STATIC_ROOT,
    ) -> None:
        self.runtime = runtime
        self.token = token
        self.static_root = static_root
        super().__init__(address, JarvisWebHandler)


class JarvisWebHandler(BaseHTTPRequestHandler):
    server: JarvisWebServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            if not self._authorized():
                return
            if parsed.path == "/api/status":
                self._send_json(HTTPStatus.OK, self.server.runtime.status())
                return
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
                query = parse_qs(parsed.query)
                try:
                    after = max(0, int(query.get("after", ["0"])[0]))
                    payload = self.server.runtime.task_snapshot(parts[2], after=after)
                    self._send_json(HTTPStatus.OK, payload)
                except (ValueError, JarvisError) as error:
                    self._send_error(error)
                return
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"ok": False, "error": {"type": "not_found", "message": "Unknown API path"}},
            )
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"ok": False, "error": {"type": "not_found", "message": "Unknown API path"}},
            )
            return
        if not self._authorized():
            return
        try:
            payload = self._read_json()
            if parsed.path == "/api/tasks":
                result = self.server.runtime.start_task(payload.get("task", ""))
                self._send_json(HTTPStatus.ACCEPTED, result)
                return
            parts = parsed.path.strip("/").split("/")
            if len(parts) == 3 and parts[:2] == ["api", "approvals"]:
                result = self.server.runtime.resolve_approval(parts[2], payload.get("approved"))
                self._send_json(HTTPStatus.OK, result)
                return
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"ok": False, "error": {"type": "not_found", "message": "Unknown API path"}},
            )
        except JarvisError as error:
            self._send_error(error)
        except (UnicodeError, json.JSONDecodeError, ValueError) as error:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"type": "invalid_request", "message": str(error)}},
            )

    def _authorized(self) -> bool:
        if secrets.compare_digest(self.headers.get("X-JARVIS-Token", ""), self.server.token):
            return True
        self._send_json(
            HTTPStatus.UNAUTHORIZED,
            {"ok": False, "error": {"type": "unauthorized", "message": "Invalid Web token"}},
        )
        return False

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("Content-Length is required")
        length = int(raw_length)
        if length < 0 or length > _MAX_REQUEST_BYTES:
            raise JarvisError(f"Request body must not exceed {_MAX_REQUEST_BYTES} bytes")
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _serve_static(self, path: str) -> None:
        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
        }
        selected = files.get(path)
        if selected is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        file_path = self.server.static_root / selected[0]
        try:
            body = file_path.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", selected[1])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, error: Exception) -> None:
        kind = getattr(error, "code", "invalid_request")
        status = (
            HTTPStatus.CONFLICT
            if isinstance(error, WebBusyError)
            else HTTPStatus.NOT_FOUND
            if isinstance(error, WebNotFoundError)
            else HTTPStatus.BAD_REQUEST
        )
        self._send_json(
            status,
            {"ok": False, "error": {"type": kind, "message": str(error)}},
        )

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_arguments: Any) -> None:
        return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis-web",
        description="Run the local-only JARVIS Web console for one workspace.",
    )
    parser.add_argument("--workspace", default=".", help="directory JARVIS may inspect and modify")
    parser.add_argument("--port", type=int, default=8765, help="localhost port (default: 8765)")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--yes", action="store_true", help="approve ordinary writes and commands")
    parser.add_argument("--allow-remote", action="store_true", help="allow sending selected data to a remote model")
    parser.add_argument("--no-session", action="store_true", help="do not save conversation history")
    parser.add_argument("--no-open", action="store_true", help="do not open the browser automatically")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.port < 0 or args.port > 65535:
            raise JarvisError("port must be between 0 and 65535")
        config = Config.from_env(workspace=args.workspace, max_turns=args.max_turns)
        config.validate_for_run()
        if not config.model_endpoint_is_local and not args.allow_remote:
            raise JarvisError(
                "Remote model endpoint selected. Re-run with --allow-remote after confirming that "
                "task text, selected files, and command output may be sent to it."
            )
        runtime = WebRuntime(
            config,
            auto_approve=args.yes,
            save_session=not args.no_session,
        )
        token = secrets.token_urlsafe(24)
        server = JarvisWebServer(("127.0.0.1", args.port), runtime, token)
        url = f"http://127.0.0.1:{server.server_port}/?token={quote(token)}"
        print(f"JARVIS Web {__version__}")
        print(f"Workspace: {config.workspace}")
        print(f"Open: {url}")
        print("Local-only server; press Ctrl+C to stop.")
        if not args.no_open:
            threading.Timer(0.25, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping JARVIS Web...")
        finally:
            server.server_close()
        return 0
    except (JarvisError, OSError) as error:
        print(f"JARVIS Web error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
