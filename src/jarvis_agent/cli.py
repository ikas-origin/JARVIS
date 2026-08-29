"""Command-line entry point for JARVIS."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__
from .agent import Agent
from .config import Config
from .errors import JarvisError
from .model_client import OpenAICompatibleClient
from .policy import Policy
from .tool_protocol import ToolRegistry
from .tools import built_in_tools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="A lightweight Coding Agent that edits files and runs local commands.",
    )
    parser.add_argument("items", nargs="*", metavar="TASK", help="programming task, or 'doctor'")
    parser.add_argument("--workspace", default=".", help="directory JARVIS may inspect and modify")
    parser.add_argument("--max-turns", type=int, default=20, help="maximum model turns (default: 20)")
    parser.add_argument("--yes", action="store_true", help="approve non-dangerous writes and commands")
    parser.add_argument("--json", action="store_true", dest="json_output", help="emit one JSON object")
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
        config.validate_for_run()
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
        agent = Agent(
            config,
            client,
            registry,
            on_event=None if args.json_output else _human_event,
        )
        task = " ".join(args.items).strip()
        if task:
            result = agent.run(task).to_dict()
            _emit(result, args.json_output)
            return 0 if result["ok"] else 2
        if args.json_output:
            raise JarvisError("Interactive mode cannot be combined with --json; provide a task")
        return _interactive(agent)
    except JarvisError as error:
        _emit_error(error.code, str(error), args.json_output)
        return 2
    except KeyboardInterrupt:
        _emit_error("cancelled", "Interrupted by user", args.json_output)
        return 130


def _interactive(agent: Agent) -> int:
    print("JARVIS interactive Coding Agent. Type /exit to quit.")
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
        print(f"\nJARVIS> {result.answer}")


def _confirm(action: str) -> bool:
    answer = input(f"\nApprove {action}? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def _human_event(name: str, data: dict[str, Any]) -> None:
    if name == "model_request":
        print(f"[turn {data['turn']}] Thinking...", file=sys.stderr)
    elif name == "tool_start":
        print(f"-> {data['name']} {json.dumps(data['arguments'], ensure_ascii=False)}", file=sys.stderr)
    elif name == "tool_end":
        marker = "ok" if data["ok"] else "error"
        preview = str(data["content"]).replace("\n", " ")[:180]
        print(f"<- {data['name']} [{marker}] {preview}", file=sys.stderr)


def _emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, ensure_ascii=False))
    elif "answer" in payload:
        print(payload["answer"])
        print(
            f"\n[{payload['status']}: {payload['stop_reason']}; "
            f"turns={payload['turns']}, tools={payload['tool_calls']}]"
        )
    else:
        print("JARVIS configuration")
        for key in ("model", "base_url", "workspace"):
            print(f"  {key}: {payload[key] or '(missing)'}")
        print(f"  api key: {'available via environment' if payload['auth']['available'] else 'missing'}")
        if payload["missing"]:
            print("  missing: " + ", ".join(payload["missing"]))


def _emit_error(kind: str, message: str, json_output: bool) -> None:
    payload = {"ok": False, "error": {"type": kind, "message": message}}
    if json_output:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"JARVIS error ({kind}): {message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())

