"""Command-line entry point for JARVIS."""

from __future__ import annotations

import argparse
from getpass import getpass
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from . import __version__
from .agent import Agent
from .config import Config, save_user_config
from .errors import JarvisError
from .model_client import OpenAICompatibleClient
from .policy import Policy
from .session import Session, SessionStore
from .spec import (
    ARTIFACTS,
    PLANNING_PHASES,
    SpecState,
    SpecStore,
    implement_prompt,
    phase_prompt,
    revise_prompt,
    verify_prompt,
)
from .terminal_ui import TerminalUI
from .tool_protocol import ToolRegistry
from .tools import built_in_tools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="A lightweight Coding Agent that edits files and runs local commands.",
        epilog=(
            "Run without TASK for the interactive Coding Agent. Inside it, use '/spec help' "
            "for the reviewed Spec -> Design -> Tasks -> Implement workflow."
        ),
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
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="acknowledge that task text, selected files, and tool output may be sent to a remote model",
    )
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
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors in human output")
    parser.add_argument("--version", action="version", version=f"JARVIS {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
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
        _require_remote_consent(config, args.allow_remote)
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
        display = None if args.json_output else HumanDisplay(color=False if args.no_color else None)
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
            _emit(
                result,
                args.json_output,
                suppress_answer=bool(display and display.consume_streamed()),
                display=display,
            )
            return 0 if result["ok"] else 2
        return _interactive(
            agent,
            session,
            session_store,
            display,
            auto_approve=args.yes,
            streaming=not args.no_stream,
        )
    except JarvisError as error:
        _emit_error(error.code, str(error), args.json_output)
        return 2
    except KeyboardInterrupt:
        _emit_error("cancelled", "Interrupted by user", args.json_output)
        return 130


def _interactive(
    agent: Agent,
    session: Session | None,
    store: SessionStore,
    display: "HumanDisplay | None",
    *,
    auto_approve: bool,
    streaming: bool,
) -> int:
    _print_interactive_header(
        agent.config,
        session,
        auto_approve=auto_approve,
        streaming=streaming,
        tool_count=len(getattr(getattr(agent, "tools", None), "schemas", [])),
        display=display,
    )
    while True:
        try:
            task = input(display.prompt() if display else "\nyou> ").strip()
        except EOFError:
            return 0
        if not task:
            continue
        if task.startswith("/"):
            should_exit = _handle_interactive_command(
                task,
                agent,
                session,
                store,
                display,
                auto_approve=auto_approve,
                streaming=streaming,
            )
            if should_exit:
                return 0
            continue
        active_spec = SpecStore(agent.config.workspace).active()
        if active_spec is not None:
            print(
                f"Spec '{active_spec.name}' is active in phase '{active_spec.phase}'. "
                "Use /spec status and the phase-specific /spec command instead of a free-form task."
            )
            continue
        result = agent.run(task)
        if display:
            display.finish_line()
        payload = result.to_dict()
        payload["session_id"] = session.id if session else None
        _emit(
            payload,
            False,
            suppress_answer=bool(display and display.consume_streamed()),
            display=display,
        )


def _print_interactive_header(
    config: Config,
    session: Session | None,
    *,
    auto_approve: bool,
    streaming: bool,
    tool_count: int,
    display: "HumanDisplay | None",
) -> None:
    branch = _git_branch(config.workspace)
    ui = display.ui if display else TerminalUI(color=False)
    active_spec = SpecStore(config.workspace).active()
    mode = f"SPEC:{active_spec.phase}" if active_spec else "REACT"
    ui.banner(
        version=__version__,
        workspace=str(config.workspace),
        model=config.model or "(missing)",
        branch=branch,
        session_id=session.id if session else None,
        approval="automatic for ordinary actions" if auto_approve else "ask before writes/commands",
        tools=tool_count,
        streaming=streaming,
        mode=mode,
    )


def _handle_interactive_command(
    raw: str,
    agent: Agent,
    session: Session | None,
    store: SessionStore,
    display: "HumanDisplay | None" = None,
    *,
    auto_approve: bool,
    streaming: bool,
) -> bool:
    command = raw.strip().lower()
    if command in {"/exit", "/quit"}:
        return True
    if command == "/help":
        print(
            "Interactive commands:\n"
            "  /status    show workspace, model, session, and context state\n"
            "  /sessions  list saved sessions\n"
            "  /clear     clear conversation context for this session\n"
            "  /spec      manage a reviewed Spec -> Design -> Tasks -> Implement workflow\n"
            "  /exit      leave JARVIS (also /quit)"
        )
        return False
    if command == "/status":
        print(f"workspace  {agent.config.workspace}")
        print(f"model      {agent.config.model}")
        print(f"git        {_git_branch(agent.config.workspace) or '(not a Git repository)'}")
        print(f"session    {session.id if session else '(not saved)'}")
        print(f"messages   {len(agent.messages)}")
        print(f"streaming  {'on' if streaming else 'off'}")
        print(f"approval   {'automatic' if auto_approve else 'ask'}")
        return False
    if command == "/sessions":
        _emit_sessions([saved.summary() for saved in store.list()], False)
        return False
    if command == "/clear":
        agent.reset_context()
        print("Conversation context cleared. Workspace files were not changed.")
        return False
    if command == "/spec" or command.startswith("/spec "):
        _handle_spec_command(raw, agent, session, display)
        return False
    print(f"Unknown command: {raw}. Type /help to see available commands.")
    return False


def _handle_spec_command(
    raw: str,
    agent: Agent,
    session: Session | None,
    display: "HumanDisplay | None",
) -> None:
    store = SpecStore(agent.config.workspace)
    parts = raw.strip().split(maxsplit=3)
    action = parts[1].lower() if len(parts) > 1 else "status"
    try:
        if action == "help":
            _print_spec_help()
            return
        if action == "list":
            _print_spec_list(store)
            return
        if action == "new":
            if len(parts) < 4:
                raise JarvisError("Usage: /spec new <name> <goal>")
            state = store.create(parts[2], parts[3])
            print(f"Created spec '{state.name}' at .jarvis/specs/{state.name}")
            _run_spec_agent(agent, session, display, state, phase_prompt(state, "requirements"), "planning")
            _report_artifact(store, state, "requirements")
            return

        state = store.active()
        if state is None:
            if action == "status":
                print("No active spec. Use /spec new <name> <goal> or /spec list.")
                return
            raise JarvisError("No active spec. Use /spec new <name> <goal> first.")
        if action == "status":
            _print_spec_status(store, state)
        elif action == "show":
            if len(parts) < 3:
                raise JarvisError("Usage: /spec show requirements|design|tasks|verification")
            print(store.read_artifact(state, parts[2].lower()))
        elif action == "generate":
            if state.phase not in PLANNING_PHASES:
                raise JarvisError(f"Nothing can be generated during phase: {state.phase}")
            _run_spec_agent(
                agent,
                session,
                display,
                state,
                phase_prompt(state, state.phase),
                "planning",
            )
            _report_artifact(store, state, state.phase)
        elif action == "revise":
            feedback = raw.strip().split(maxsplit=2)[2] if len(raw.strip().split(maxsplit=2)) > 2 else ""
            if not feedback:
                raise JarvisError("Usage: /spec revise <feedback>")
            _run_spec_agent(
                agent,
                session,
                display,
                state,
                revise_prompt(state, feedback),
                "planning",
            )
            _report_artifact(store, state, state.phase)
        elif action == "approve":
            next_phase = store.approve(state)
            print(f"Approved {state.approvals[-1]}; spec phase is now {next_phase}.")
            if next_phase in {"design", "tasks"}:
                _run_spec_agent(
                    agent,
                    session,
                    display,
                    state,
                    phase_prompt(state, next_phase),
                    "planning",
                )
                _report_artifact(store, state, next_phase)
            else:
                print("Planning gates passed. Use /spec implement to execute the next task.")
        elif action == "implement":
            _implement_next_spec_task(store, state, agent, session, display)
        elif action == "verify":
            _verify_spec(store, state, agent, session, display)
        elif action == "cancel":
            store.set_phase(state, "cancelled")
            print(f"Cancelled spec '{state.name}'. Its artifacts were preserved.")
        else:
            _print_spec_help()
    except JarvisError as error:
        print(f"Spec error: {error}")


def _run_spec_agent(
    agent: Agent,
    session: Session | None,
    display: "HumanDisplay | None",
    state: SpecState,
    prompt: str,
    mode: str,
) -> None:
    policy = agent.tools.policy
    spec_store = SpecStore(agent.config.workspace)
    spec_directory = spec_store.directory(state.name)
    if mode == "planning":
        artifact = spec_store.artifact_path(state, state.phase)
        policy.restrict(write_roots=(artifact,), commands_allowed=False)
    elif mode == "verifying":
        artifact = spec_store.artifact_path(state, "verification")
        policy.restrict(write_roots=(artifact,), commands_allowed=True)
    else:
        policy.restrict(
            write_roots=None,
            commands_allowed=True,
            denied_write_paths=(
                spec_store.artifact_path(state, "requirements"),
                spec_store.artifact_path(state, "design"),
                spec_store.artifact_path(state, "verification"),
                spec_directory / "state.json",
            ),
        )
    try:
        result = agent.run(prompt)
    finally:
        policy.clear_restrictions()
    if display:
        display.finish_line()
    payload = result.to_dict()
    payload["session_id"] = session.id if session else None
    _emit(
        payload,
        False,
        suppress_answer=bool(display and display.consume_streamed()),
        display=display,
    )


def _implement_next_spec_task(
    store: SpecStore,
    state: SpecState,
    agent: Agent,
    session: Session | None,
    display: "HumanDisplay | None",
) -> None:
    if state.phase != "implementing":
        raise JarvisError(f"Spec must be in implementing phase, currently: {state.phase}")
    task = store.next_task(state)
    if task is None:
        if store.all_tasks_complete(state):
            store.set_phase(state, "verifying")
            print("All tasks are checked. Use /spec verify.")
            return
        raise JarvisError("tasks.md contains no recognizable '- [ ]' tasks")
    print(f"Implementing next task: {task}")
    _run_spec_agent(agent, session, display, state, implement_prompt(state, task), "implementing")
    if store.all_tasks_complete(state):
        store.set_phase(state, "verifying")
        print("All tasks are complete. Use /spec verify for final traceability and tests.")
    elif store.next_task(state) == task:
        print("The task remains unchecked because successful verification was not recorded.")
    else:
        print("Task completed. Use /spec implement for the next task.")


def _verify_spec(
    store: SpecStore,
    state: SpecState,
    agent: Agent,
    session: Session | None,
    display: "HumanDisplay | None",
) -> None:
    if state.phase != "verifying":
        raise JarvisError(f"Spec must be in verifying phase, currently: {state.phase}")
    if not store.all_tasks_complete(state):
        raise JarvisError("All tasks must be checked before final verification")
    _run_spec_agent(agent, session, display, state, verify_prompt(state), "verifying")
    if store.verification_passed(state):
        store.set_phase(state, "completed")
        print(f"Spec '{state.name}' completed with verification status PASS.")
    else:
        remediation = store.add_verification_fix_task(state)
        store.set_phase(state, "implementing")
        print(
            "Verification did not pass. Returned to implementing with remediation task: "
            + remediation
        )


def _report_artifact(store: SpecStore, state: SpecState, kind: str) -> None:
    path = store.artifact_path(state, kind)
    if path.is_file():
        print(f"Review {path.relative_to(store.workspace)} then use /spec approve or /spec revise.")
    else:
        print(f"Artifact {kind} was not created. Use /spec generate to retry.")


def _print_spec_status(store: SpecStore, state: SpecState) -> None:
    print(f"spec       {state.name}")
    print(f"phase      {state.phase}")
    print(f"goal       {state.goal}")
    print(f"approvals  {', '.join(state.approvals) or '(none)'}")
    for kind, filename in ARTIFACTS.items():
        exists = (store.directory(state.name) / filename).is_file()
        print(f"{kind:<12}{'ready' if exists else 'missing'}")
    if state.phase == "implementing":
        print(f"next task  {store.next_task(state) or '(none)'}")


def _print_spec_list(store: SpecStore) -> None:
    states = store.list()
    if not states:
        print("No JARVIS specs in this workspace.")
        return
    for state in states:
        print(f"{state.name:<24} {state.phase:<13} {state.updated_at}")


def _print_spec_help() -> None:
    print(
        "Spec commands:\n"
        "  /spec new <name> <goal>  create a spec and draft requirements\n"
        "  /spec status             show active phase and artifacts\n"
        "  /spec list               list workspace specs\n"
        "  /spec show <artifact>    print requirements, design, tasks, or verification\n"
        "  /spec generate           retry the current planning artifact\n"
        "  /spec revise <feedback>  revise the current planning artifact\n"
        "  /spec approve            approve requirements/design/tasks and advance\n"
        "  /spec implement          implement and verify the next unchecked task\n"
        "  /spec verify             run final verification and traceability\n"
        "  /spec cancel             stop the workflow but preserve artifacts"
    )


def _git_branch(workspace: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    branch = completed.stdout.strip()
    return branch if completed.returncode == 0 and branch else None


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
    try:
        answer = input(f"\nApprove {action}? [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def _require_remote_consent(config: Config, allow_remote: bool) -> None:
    if config.model_endpoint_is_local or allow_remote:
        return
    raise JarvisError(
        "The configured model endpoint is remote. JARVIS may send it task text, selected workspace "
        "files, and command output. Review the provider's data policy, then rerun with --allow-remote "
        "to acknowledge this for the current invocation."
    )


def _configure_stdio() -> None:
    """Use stable UTF-8 output for Windows terminals, pipes, and JSON capture."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


class HumanDisplay:
    def __init__(self, *, color: bool | None = None) -> None:
        self.ui = TerminalUI(color=color)
        self.line_open = False
        self.streamed = False

    def prompt(self) -> str:
        return self.ui.prompt()

    def __call__(self, name: str, data: dict[str, Any]) -> None:
        if name == "assistant_delta":
            if not self.line_open:
                self.ui.assistant_header()
                self.line_open = True
            print(data["text"], end="", flush=True)
            self.streamed = True
        elif name == "model_request":
            self.finish_line()
            self.ui.thinking(data["turn"])
        elif name == "context_trimmed":
            self.ui.context_trimmed(
                data["before_messages"],
                data["after_messages"],
                data.get("before_chars"),
                data.get("after_chars"),
            )
        elif name == "verification_required":
            self.finish_line()
            self.ui.verification_required()
        elif name == "tool_start":
            self.finish_line()
            self.ui.tool_start(data["name"], data["arguments"])
        elif name == "tool_end":
            self.ui.tool_end(
                data["name"],
                data["ok"],
                data["content"],
                data.get("metadata", {}),
            )

    def finish_line(self) -> None:
        if self.line_open:
            print()
            self.ui.assistant_footer()
            self.line_open = False

    def consume_streamed(self) -> bool:
        value = self.streamed
        self.streamed = False
        return value


def _emit(
    payload: dict[str, Any],
    json_output: bool,
    *,
    suppress_answer: bool = False,
    display: HumanDisplay | None = None,
) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False))
    elif "answer" in payload:
        if display:
            if not suppress_answer:
                display.ui.answer(payload["answer"])
            display.ui.summary(payload)
        else:
            if not suppress_answer:
                print(payload["answer"])
            print(
                f"\n[{payload['status']}: {payload['stop_reason']}; "
                f"turns={payload['turns']}, tools={payload['tool_calls']}, "
                f"tokens={payload['usage'].get('total_tokens', 'n/a')}, "
                f"verification={payload['verification_status']}, "
                f"elapsed={payload['elapsed_seconds']:.3f}s]"
            )
    else:
        print("JARVIS configuration")
        for key in ("model", "base_url", "model_endpoint", "workspace"):
            print(f"  {key}: {payload[key] or '(missing)'}")
        key_status = (
            f"available via {payload['auth']['source']}" if payload["auth"]["available"] else "missing"
        )
        print(f"  api key: {key_status}")
        print(f"  auth source: {payload['auth']['source']}")
        print(f"  config file: {payload['config_path']}")
        if payload["remote_data_notice"]:
            print(f"  data notice: {payload['remote_data_notice']}")
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
