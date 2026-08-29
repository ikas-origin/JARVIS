"""Command-line entry point for JARVIS."""

from __future__ import annotations

import argparse
from getpass import getpass
import json
import sys
from typing import Any

from . import __version__
from .agent import Agent
from .config import Config, save_user_config
from .errors import JarvisError
from .model_client import OpenAICompatibleClient
from .policy import Policy
from .session import Session, SessionStore
from .tool_protocol import ToolRegistry
from .tools import built_in_tools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="A lightweight Coding Agent that edits files and runs local commands.",
    )
    parser.add_argument(
        "items",
        nargs="*",
        metavar="TASK",
        help="programming task, 'doctor', 'configure', or 'sessions'",
    )
    parser.add_argument("--workspace", default=".", help="directory JARVIS may inspect and modify")
    parser.add_argument("--max-turns", type=int, default=20, help="maximum model turns (default: 20)")
    parser.add_argument("--yes", action="store_true", help="approve non-dangerous writes and commands")
    parser.add_argument("--json", action="store_true", dest="json_output", help="emit one JSON object")
    session_group = parser.add_mutually_exclusive_group()
    session_group.add_argument(
        "--continue",
        action="store_true",
        dest="continue_session",
        help="continue the most recent session for this workspace",
    )
    session_group.add_argument("--resume", metavar="SESSION_ID", help="resume one exact session")
    parser.add_argument("--no-session", action="store_true", help="do not save conversation history")
    parser.add_argument("--no-stream", action="store_true", help="wait for each complete model response")
    parser.add_argument("--version", action="version", version=f"JARVIS {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = Config.from_env(workspace=args.workspace, max_turns=args.max_turns)
        if args.items == ["doctor"]:
            result = config.doctor()
            _emit(result, args.json_output)
            return 0 if result["ok"] else 1
        if args.items == ["configure"]:
            if args.json_output:
                raise JarvisError("configure is interactive and cannot be combined with --json")
            return _configure(config)
        session_store = SessionStore(config.config_path.parent / "sessions")
        if args.items == ["sessions"]:
            sessions = [session.summary() for session in session_store.list()]
            _emit_sessions(sessions, args.json_output)
            return 0
        if args.no_session and (args.continue_session or args.resume):
            raise JarvisError("--no-session cannot be combined with --continue or --resume")
        config.validate_for_run()
        task = " ".join(args.items).strip()
        if not task and args.json_output:
            raise JarvisError("Interactive mode cannot be combined with --json; provide a task")
        client = OpenAICompatibleClient(
            api_key=config.api_key or "",
            model=config.model or "",
            base_url=config.base_url,
            timeout=config.request_timeout,
        )
        confirm = None if args.json_output else _confirm
        registry = ToolRegistry(
            built_in_tools(
                command_timeout=config.command_timeout,
                output_limit=config.max_tool_output_chars,
            ),
            Policy(config.workspace, auto_approve=args.yes, confirm=confirm),
        )
        session = _select_session(session_store, config, args)
        checkpoint = None
        initial_messages = None
        if session is not None:
            initial_messages = session.messages or None

            def save_messages(messages, *, _session=session, _store=session_store):
                _session.messages = messages
                _store.save(_session)

            checkpoint = save_messages
        display = None if args.json_output else HumanDisplay()
        agent = Agent(
            config,
            client,
            registry,
            on_event=display,
            initial_messages=initial_messages,
            checkpoint=checkpoint,
            stream=not args.json_output and not args.no_stream,
        )
        if task:
            result = agent.run(task).to_dict()
            result["session_id"] = session.id if session else None
            if display:
                display.finish_line()
            _emit(result, args.json_output, suppress_answer=bool(display and display.consume_streamed()))
            return 0 if result["ok"] else 2
        return _interactive(agent, session.id if session else None, display)
    except JarvisError as error:
        _emit_error(error.code, str(error), args.json_output)
        return 2
    except KeyboardInterrupt:
        _emit_error("cancelled", "Interrupted by user", args.json_output)
        return 130


def _interactive(agent: Agent, session_id: str | None, display: "HumanDisplay | None") -> int:
    suffix = f" Session: {session_id}." if session_id else " Session saving is disabled."
    print("JARVIS interactive Coding Agent." + suffix + " Type /exit to quit.")
    while True:
        try:
            task = input("\nYou> ").strip()
        except EOFError:
            return 0
        if task in {"/exit", "/quit"}:
            return 0
        if not task:
            continue
        result = agent.run(task)
        if display:
            display.finish_line()
        if not display or not display.consume_streamed():
            print(f"\nJARVIS> {result.answer}")


def _configure(config: Config) -> int:
    print(f"JARVIS configuration file: {config.config_path}")
    current_key_hint = " (press Enter to keep the saved key)" if config.auth_source == "config" else ""
    api_key = getpass(f"API key{current_key_hint}: ").strip() or config.api_key or ""
    model_default = config.model or ""
    model_prompt = f"Model [{model_default}]: " if model_default else "Model: "
    model = input(model_prompt).strip() or model_default
    base_url = input(f"Base URL [{config.base_url}]: ").strip() or config.base_url
    saved_path = save_user_config(
        api_key=api_key,
        model=model,
        base_url=base_url,
        path=config.config_path,
    )
    # Reuse validation rules before reporting a successful configuration.
    Config.from_env(workspace=config.workspace, config_path=saved_path).validate_for_run()
    print(f"Saved JARVIS configuration to {saved_path}")
    print("The API key was stored but will never be printed by JARVIS.")
    return 0


def _select_session(store: SessionStore, config: Config, args) -> Session | None:
    if args.no_session:
        return None
    if args.resume:
        return store.load(args.resume, workspace=config.workspace)
    if args.continue_session:
        session = store.latest(config.workspace)
        if session is None:
            raise JarvisError(f"No saved session exists for workspace: {config.workspace}")
        return session
    return store.create(config.workspace)


def _confirm(action: str) -> bool:
    answer = input(f"\nApprove {action}? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


class HumanDisplay:
    def __init__(self) -> None:
        self.line_open = False
        self.streamed = False

    def __call__(self, name: str, data: dict[str, Any]) -> None:
        if name == "assistant_delta":
            if not self.line_open:
                print("JARVIS> ", end="", flush=True)
                self.line_open = True
            print(data["text"], end="", flush=True)
            self.streamed = True
        elif name == "model_request":
            self.finish_line()
            print(f"[turn {data['turn']}] Thinking...", file=sys.stderr)
        elif name == "tool_start":
            self.finish_line()
            print(f"-> {data['name']} {json.dumps(data['arguments'], ensure_ascii=False)}", file=sys.stderr)
        elif name == "tool_end":
            marker = "ok" if data["ok"] else "error"
            preview = str(data["content"]).replace("\n", " ")[:180]
            print(f"<- {data['name']} [{marker}] {preview}", file=sys.stderr)

    def finish_line(self) -> None:
        if self.line_open:
            print()
            self.line_open = False

    def consume_streamed(self) -> bool:
        value = self.streamed
        self.streamed = False
        return value


def _emit(payload: dict[str, Any], json_output: bool, *, suppress_answer: bool = False) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False))
    elif "answer" in payload:
        if not suppress_answer:
            print(payload["answer"])
        print(
            f"\n[{payload['status']}: {payload['stop_reason']}; "
            f"turns={payload['turns']}, tools={payload['tool_calls']}, "
            f"tokens={payload['usage'].get('total_tokens', 'n/a')}, "
            f"elapsed={payload['elapsed_seconds']:.3f}s]"
        )
    else:
        print("JARVIS configuration")
        for key in ("model", "base_url", "workspace"):
            print(f"  {key}: {payload[key] or '(missing)'}")
        key_status = (
            f"available via {payload['auth']['source']}" if payload["auth"]["available"] else "missing"
        )
        print(f"  api key: {key_status}")
        print(f"  auth source: {payload['auth']['source']}")
        print(f"  config file: {payload['config_path']}")
        if payload["missing"]:
            print("  missing: " + ", ".join(payload["missing"]))


def _emit_error(kind: str, message: str, json_output: bool) -> None:
    payload = {"ok": False, "error": {"type": kind, "message": message}}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"JARVIS error ({kind}): {message}", file=sys.stderr)


def _emit_sessions(sessions: list[dict[str, Any]], json_output: bool) -> None:
    if json_output:
        print(json.dumps({"ok": True, "sessions": sessions}, ensure_ascii=False))
        return
    if not sessions:
        print("No saved JARVIS sessions.")
        return
    for session in sessions:
        print(
            f"{session['id']}  {session['updated_at']}  "
            f"messages={session['message_count']}  {session['workspace']}"
        )
        if session["last_task"]:
            print(f"  {session['last_task']}")


if __name__ == "__main__":
    raise SystemExit(main())
