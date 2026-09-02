"""Bounded local command execution."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
from typing import Any

from ..policy import Policy
from ..tool_protocol import Tool
from ..types import ToolResult


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    marker = "\n... output truncated ...\n"
    if limit <= len(marker):
        return marker[:limit], True
    remaining = limit - len(marker)
    head = remaining // 2
    tail = remaining - head
    return text[:head] + marker + text[-tail:], True


def _as_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def make_run_command_tool(timeout: float, output_limit: int) -> Tool:
    def run_command(arguments: dict[str, Any], policy: Policy) -> ToolResult:
        command = arguments["command"]
        purpose = arguments["purpose"]
        requested_timeout = float(arguments.get("timeout", timeout))
        requested_timeout = min(max(requested_timeout, 1.0), 300.0)
        policy.check_command(command)
        child_env = _sanitized_environment()
        process = subprocess.Popen(
            command,
            cwd=policy.workspace,
            env=child_env,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            ),
            start_new_session=os.name != "nt",
        )
        windows_job = _assign_windows_job(process)
        try:
            try:
                stdout, stderr = process.communicate(timeout=requested_timeout)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(process, windows_job)
                stdout, stderr = process.communicate()
                partial = _as_text(stdout) + _as_text(stderr)
                output, truncated = _truncate(partial, output_limit)
                return ToolResult(
                    False,
                    output or f"Command timed out after {requested_timeout:g} seconds",
                    {"timed_out": True, "truncated": truncated, "purpose": purpose},
                )
        finally:
            _close_windows_job(windows_job)
        combined = stdout
        if stderr:
            combined += ("\n" if combined else "") + "[stderr]\n" + stderr
        output, truncated = _truncate(combined.rstrip(), output_limit)
        return ToolResult(
            process.returncode == 0,
            output,
            {"exit_code": process.returncode, "truncated": truncated, "purpose": purpose},
        )

    return Tool(
        "run_command",
        (
            "Run a local shell command in the workspace. Set purpose='inspect' for discovery and "
            "purpose='verify' only for a test, build, lint, type-check, or other executable validation."
        ),
        {
            "type": "object",
            "properties": {
                "command": {"type": "string", "minLength": 1},
                "purpose": {
                    "type": "string",
                    "enum": ["inspect", "verify"],
                    "description": "inspect gathers information; verify supplies post-change evidence",
                },
                "timeout": {
                    "type": "number",
                    "minimum": 1,
                    "maximum": 300,
                    "description": "Seconds",
                },
            },
            "required": ["command", "purpose"],
            "additionalProperties": False,
        },
        run_command,
    )


def _assign_windows_job(process: subprocess.Popen[str]) -> tuple[Any, Any] | None:
    """Put a Windows command in a kill-on-close job so descendants cannot escape."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None
        information = ExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = 0x00002000
        configured = kernel32.SetInformationJobObject(
            handle,
            9,
            ctypes.byref(information),
            ctypes.sizeof(information),
        )
        assigned = configured and kernel32.AssignProcessToJobObject(handle, process._handle)
        if not assigned:
            kernel32.CloseHandle(handle)
            return None
        return kernel32, handle
    except (AttributeError, OSError, TypeError):
        return None


def _close_windows_job(job: tuple[Any, Any] | None) -> None:
    if job is not None:
        job[0].CloseHandle(job[1])


def _terminate_process_tree(
    process: subprocess.Popen[str], windows_job: tuple[Any, Any] | None = None
) -> None:
    """Terminate the shell and descendants so a timeout is a real boundary."""
    if windows_job is not None and windows_job[0].TerminateJobObject(windows_job[1], 1):
        return
    if os.name == "nt":
        try:
            terminated = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
            if terminated.returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
            return
        except (OSError, ProcessLookupError):
            pass
    if process.poll() is None:
        process.kill()


_SECRET_ENV_NAME = re.compile(
    r"(?:^|_)(?:API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?|PRIVATE_?KEY)(?:$|_)",
    re.IGNORECASE,
)


def _sanitized_environment() -> dict[str, str]:
    """Keep normal build variables while withholding common credential names."""
    environment = {
        name: value for name, value in os.environ.items() if not _SECRET_ENV_NAME.search(name)
    }
    interpreter_dir = os.path.dirname(os.path.abspath(sys.executable))
    path = environment.get("PATH", "")
    path_entries = path.split(os.pathsep) if path else []
    normalized_entries = {os.path.normcase(os.path.abspath(entry)) for entry in path_entries if entry}
    if os.path.normcase(interpreter_dir) not in normalized_entries:
        environment["PATH"] = (
            interpreter_dir + (os.pathsep + path if path else "")
        )
    return environment
