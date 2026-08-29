"""Repository-local Spec-Driven Development state and artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from .errors import ConfigurationError


SPEC_VERSION = 1
PHASES = (
    "requirements",
    "design",
    "tasks",
    "implementing",
    "verifying",
    "completed",
    "cancelled",
)
PLANNING_PHASES = {"requirements", "design", "tasks"}
ARTIFACTS = {
    "requirements": "requirements.md",
    "design": "design.md",
    "tasks": "tasks.md",
    "verification": "verification.md",
}
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_TASK = re.compile(r"^\s*-\s*\[([ xX])\]\s*(.+)$", re.MULTILINE)
_PASS = re.compile(r"^Status:\s*PASS\s*$", re.IGNORECASE | re.MULTILINE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SpecState:
    name: str
    goal: str
    phase: str
    created_at: str
    updated_at: str
    approvals: list[str]
    version: int = SPEC_VERSION

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "goal": self.goal,
            "phase": self.phase,
            "approvals": list(self.approvals),
            "updated_at": self.updated_at,
        }


class SpecStore:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.root = (self.workspace / ".jarvis" / "specs").resolve(strict=False)
        try:
            self.root.relative_to(self.workspace)
        except ValueError as error:
            raise ConfigurationError("Spec directory escapes workspace through a symbolic link") from error

    def create(self, name: str, goal: str) -> SpecState:
        name = name.strip().lower()
        goal = goal.strip()
        if not _SLUG.fullmatch(name):
            raise ConfigurationError(
                "Spec name must start with a lowercase letter or digit and contain only a-z, 0-9, or '-'"
            )
        if not goal:
            raise ConfigurationError("Spec goal must not be empty")
        if self.active() is not None:
            raise ConfigurationError(
                f"An unfinished spec is already active: {self.active().name}"
            )
        directory = self.directory(name)
        if directory.exists():
            raise ConfigurationError(f"Spec already exists: {name}")
        timestamp = _now()
        state = SpecState(name, goal, "requirements", timestamp, timestamp, [])
        directory.mkdir(parents=True)
        self.save(state)
        return state

    def save(self, state: SpecState) -> None:
        if state.phase not in PHASES:
            raise ConfigurationError(f"Invalid spec phase: {state.phase}")
        state.updated_at = _now()
        directory = self.directory(state.name)
        directory.mkdir(parents=True, exist_ok=True)
        _atomic_json(directory / "state.json", asdict(state))

    def load(self, name: str) -> SpecState:
        path = self.directory(name) / "state.json"
        if not path.is_file():
            raise ConfigurationError(f"Spec not found: {name}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            state = SpecState(**payload)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as error:
            raise ConfigurationError(f"Cannot load spec {name}: {error}") from error
        if (
            state.version != SPEC_VERSION
            or state.name != name
            or not state.goal.strip()
            or state.phase not in PHASES
            or not isinstance(state.approvals, list)
            or any(approval not in PLANNING_PHASES for approval in state.approvals)
        ):
            raise ConfigurationError(f"Unsupported spec state: {name}")
        return state

    def list(self) -> list[SpecState]:
        if not self.root.is_dir():
            return []
        states: list[SpecState] = []
        for path in self.root.glob("*/state.json"):
            try:
                states.append(self.load(path.parent.name))
            except ConfigurationError:
                continue
        return sorted(states, key=lambda state: state.updated_at, reverse=True)

    def active(self) -> SpecState | None:
        return next(
            (state for state in self.list() if state.phase not in {"completed", "cancelled"}),
            None,
        )

    def directory(self, name: str) -> Path:
        if not _SLUG.fullmatch(name):
            raise ConfigurationError(f"Invalid spec name: {name}")
        candidate = (self.root / name).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise ConfigurationError(f"Spec directory escapes workspace: {name}") from error
        return candidate

    def artifact_path(self, state: SpecState, kind: str) -> Path:
        filename = ARTIFACTS.get(kind)
        if filename is None:
            raise ConfigurationError(f"Unknown spec artifact: {kind}")
        return self.directory(state.name) / filename

    def read_artifact(self, state: SpecState, kind: str) -> str:
        path = self.artifact_path(state, kind)
        if not path.is_file():
            raise ConfigurationError(f"Spec artifact does not exist yet: {kind}")
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ConfigurationError(f"Cannot read spec artifact {path}: {error}") from error

    def approve(self, state: SpecState) -> str:
        transitions = {"requirements": "design", "design": "tasks", "tasks": "implementing"}
        next_phase = transitions.get(state.phase)
        if next_phase is None:
            raise ConfigurationError(f"Spec phase cannot be approved: {state.phase}")
        self.read_artifact(state, state.phase)
        if state.phase not in state.approvals:
            state.approvals.append(state.phase)
        state.phase = next_phase
        self.save(state)
        return next_phase

    def set_phase(self, state: SpecState, phase: str) -> None:
        if phase not in PHASES:
            raise ConfigurationError(f"Invalid spec phase: {phase}")
        state.phase = phase
        self.save(state)

    def next_task(self, state: SpecState) -> str | None:
        content = self.read_artifact(state, "tasks")
        return next((text.strip() for mark, text in _TASK.findall(content) if mark == " "), None)

    def all_tasks_complete(self, state: SpecState) -> bool:
        matches = _TASK.findall(self.read_artifact(state, "tasks"))
        return bool(matches) and all(mark.lower() == "x" for mark, _text in matches)

    def verification_passed(self, state: SpecState) -> bool:
        return bool(_PASS.search(self.read_artifact(state, "verification")))

    def add_verification_fix_task(self, state: SpecState) -> str:
        path = self.artifact_path(state, "tasks")
        content = self.read_artifact(state, "tasks").rstrip()
        existing = [
            int(value)
            for value in re.findall(r"^\s*-\s*\[[ xX]\]\s*TV(\d+)\b", content, re.MULTILINE)
        ]
        task_id = f"TV{max(existing, default=0) + 1}"
        task = (
            f"{task_id} Resolve failures documented in verification.md and rerun affected checks"
        )
        path.write_text(content + f"\n- [ ] {task}\n", encoding="utf-8", newline="")
        return task


def phase_prompt(state: SpecState, kind: str) -> str:
    relative = f".jarvis/specs/{state.name}/{ARTIFACTS[kind]}"
    common = (
        f"You are working in JARVIS Spec mode for '{state.name}'. Goal: {state.goal}\n"
        "Inspect the existing repository with read-only tools before drafting. "
        "Do not modify application code and do not run commands in this planning phase. "
    )
    if kind == "requirements":
        return common + (
            f"Create {relative}. Define scope, non-goals, numbered requirements, and testable acceptance "
            "criteria with stable IDs such as R1 and AC-R1-1. Do not choose implementation details yet. "
            "Use the same natural language as the goal when practical. Write the artifact with write_file, "
            "then summarize uncertainties for human review."
        )
    if kind == "design":
        return common + (
            f"Read requirements.md and create {relative}. Describe architecture, components, data flow, "
            "interfaces, error handling, security, and test strategy. Map design decisions to requirement "
            "IDs. Write the artifact with write_file, then summarize tradeoffs for human review."
        )
    if kind == "tasks":
        return common + (
            f"Read requirements.md and design.md and create {relative}. Use Markdown tasks exactly in the "
            "form '- [ ] T1 description'. Each task must reference requirement IDs and include a concrete "
            "verification command or observable result. Order tasks by dependency and keep them small enough "
            "for one focused agent iteration. Write the artifact with write_file."
        )
    raise ConfigurationError(f"Cannot generate artifact: {kind}")


def revise_prompt(state: SpecState, feedback: str) -> str:
    kind = state.phase
    if kind not in PLANNING_PHASES:
        raise ConfigurationError(f"Spec cannot be revised during phase: {kind}")
    relative = f".jarvis/specs/{state.name}/{ARTIFACTS[kind]}"
    return (
        f"Revise the active JARVIS spec artifact {relative}. Human feedback: {feedback}\n"
        "Read the existing artifact and earlier approved artifacts. Modify only the active spec directory; "
        "do not modify application code and do not run commands. Preserve stable requirement/task IDs where "
        "possible and summarize what changed."
    )


def implement_prompt(state: SpecState, task: str) -> str:
    return (
        f"Implement exactly this task from .jarvis/specs/{state.name}/tasks.md:\n{task}\n\n"
        "First read requirements.md, design.md, tasks.md, and verification.md when it exists. Make focused "
        "application-code changes, run the "
        "task's verification, and fix failures. Only after verification succeeds, edit tasks.md to change this "
        "task's checkbox from [ ] to [x]. Do not mark other tasks complete. Report files changed and evidence."
    )


def verify_prompt(state: SpecState) -> str:
    path = f".jarvis/specs/{state.name}/verification.md"
    return (
        f"Verify the completed spec '{state.name}'. Read requirements.md, design.md, and tasks.md; inspect the "
        "implementation and run relevant tests. Create " + path + " with a requirement traceability table, "
        "commands run, failures, and remaining limitations. Include a line exactly 'Status: PASS' only when "
        "every acceptance criterion is supported by implementation and successful evidence; otherwise include "
        "'Status: FAIL'. Do not hide failures or change requirements to make verification pass."
    )


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix="state-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
        os.replace(temporary_name, path)
    except OSError as error:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise ConfigurationError(f"Cannot save spec state {path}: {error}") from error
