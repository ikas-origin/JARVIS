"""Small Tkinter launcher for the JARVIS CLI."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk


def build_cli_command(
    *,
    python: str,
    workspace: str,
    task: str,
    max_turns: int,
    auto_approve: bool,
    continue_session: bool,
    allow_remote: bool = False,
) -> list[str]:
    command = [
        python,
        "-m",
        "jarvis_agent",
        "--workspace",
        workspace,
        "--max-turns",
        str(max_turns),
    ]
    if auto_approve:
        command.append("--yes")
    if allow_remote:
        command.append("--allow-remote")
    if continue_session:
        command.append("--continue")
    command.append(task)
    return command


class JarvisGUI:
    def __init__(self, root: tk.Tk, workspace: str) -> None:
        self.root = root
        self.root.title("JARVIS Coding Agent")
        self.root.geometry("960x720")
        self.root.minsize(760, 560)
        self.process: subprocess.Popen[str] | None = None
        self.output_queue: queue.Queue[str | None] = queue.Queue()

        self.workspace = tk.StringVar(value=str(Path(workspace).expanduser().resolve()))
        self.auto_approve = tk.BooleanVar(value=True)
        self.continue_session = tk.BooleanVar(value=False)
        self.allow_remote = tk.BooleanVar(value=False)
        self.max_turns = tk.IntVar(value=20)
        self.status = tk.StringVar(value="Ready")

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(80, self._drain_output)

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(outer, text="Workspace").grid(row=0, column=0, sticky="w")
        ttk.Entry(outer, textvariable=self.workspace).grid(
            row=1, column=0, columnspan=4, sticky="ew", padx=(0, 8)
        )
        ttk.Button(outer, text="Browse...", command=self._browse).grid(row=1, column=4, sticky="ew")

        ttk.Label(outer, text="Coding task").grid(row=2, column=0, sticky="w", pady=(12, 0))
        self.task = scrolledtext.ScrolledText(outer, height=7, wrap=tk.WORD)
        self.task.grid(row=3, column=0, columnspan=5, sticky="nsew")
        self.task.insert(
            "1.0",
            "阅读项目，完成指定编程任务，运行相关测试，并报告修改和验证结果。不要修改无关文件。",
        )

        options = ttk.Frame(outer)
        options.grid(row=4, column=0, columnspan=5, sticky="ew", pady=10)
        ttk.Checkbutton(options, text="自动批准普通写入和命令 (--yes)", variable=self.auto_approve).pack(
            side=tk.LEFT
        )
        ttk.Checkbutton(options, text="继续当前项目最近会话", variable=self.continue_session).pack(
            side=tk.LEFT, padx=(16, 0)
        )
        ttk.Checkbutton(
            options,
            text="允许向远程模型发送项目上下文",
            variable=self.allow_remote,
        ).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Label(options, text="最大轮次:").pack(side=tk.LEFT, padx=(16, 4))
        ttk.Spinbox(options, from_=1, to=100, textvariable=self.max_turns, width=5).pack(side=tk.LEFT)

        buttons = ttk.Frame(outer)
        buttons.grid(row=5, column=0, columnspan=5, sticky="ew")
        self.run_button = ttk.Button(buttons, text="Run JARVIS", command=self._run)
        self.run_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(buttons, text="Stop", command=self._stop, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=8)
        ttk.Button(buttons, text="Check config", command=self._doctor).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Clear output", command=self._clear).pack(side=tk.LEFT, padx=8)
        ttk.Label(buttons, textvariable=self.status).pack(side=tk.RIGHT)

        ttk.Label(outer, text="Output").grid(row=6, column=0, sticky="w", pady=(12, 0))
        self.output = scrolledtext.ScrolledText(outer, height=20, wrap=tk.WORD, state=tk.DISABLED)
        self.output.grid(row=7, column=0, columnspan=5, sticky="nsew")

        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=0)
        outer.rowconfigure(7, weight=1)

    def _browse(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.workspace.get() or str(Path.cwd()))
        if selected:
            self.workspace.set(selected)

    def _run(self) -> None:
        workspace = Path(self.workspace.get()).expanduser().resolve()
        task = self.task.get("1.0", tk.END).strip()
        if not workspace.is_dir():
            messagebox.showerror("JARVIS", f"Workspace does not exist:\n{workspace}")
            return
        if not task:
            messagebox.showerror("JARVIS", "Please enter a coding task.")
            return
        command = build_cli_command(
            python=sys.executable,
            workspace=str(workspace),
            task=task,
            max_turns=max(1, int(self.max_turns.get())),
            auto_approve=self.auto_approve.get(),
            continue_session=self.continue_session.get(),
            allow_remote=self.allow_remote.get(),
        )
        self._start(command, workspace)

    def _doctor(self) -> None:
        self._start([sys.executable, "-m", "jarvis_agent", "doctor"], Path.cwd())

    def _start(self, command: list[str], cwd: Path) -> None:
        if self.process is not None:
            messagebox.showinfo("JARVIS", "A task is already running.")
            return
        self._append(f"\n$ {' '.join(_display_argument(part) for part in command)}\n\n")
        child_env = os.environ.copy()
        child_env["PYTHONUNBUFFERED"] = "1"
        try:
            self.process = subprocess.Popen(
                command,
                cwd=cwd,
                env=child_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            self.process = None
            messagebox.showerror("JARVIS", f"Cannot start JARVIS:\n{error}")
            return
        self.status.set("Running")
        self.run_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        threading.Thread(target=self._read_process, daemon=True).start()

    def _read_process(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        for chunk in iter(lambda: self.process.stdout.read(1), ""):
            self.output_queue.put(chunk)
        exit_code = self.process.wait()
        self.output_queue.put(f"\n\n[process exited with code {exit_code}]\n")
        self.output_queue.put(None)

    def _drain_output(self) -> None:
        try:
            while True:
                item = self.output_queue.get_nowait()
                if item is None:
                    self.process = None
                    self.status.set("Ready")
                    self.run_button.configure(state=tk.NORMAL)
                    self.stop_button.configure(state=tk.DISABLED)
                else:
                    self._append(item)
        except queue.Empty:
            pass
        self.root.after(80, self._drain_output)

    def _append(self, text: str) -> None:
        self.output.configure(state=tk.NORMAL)
        self.output.insert(tk.END, text)
        self.output.see(tk.END)
        self.output.configure(state=tk.DISABLED)

    def _clear(self) -> None:
        self.output.configure(state=tk.NORMAL)
        self.output.delete("1.0", tk.END)
        self.output.configure(state=tk.DISABLED)

    def _stop(self) -> None:
        if self.process is not None:
            self.status.set("Stopping...")
            self.process.terminate()

    def _close(self) -> None:
        if self.process is not None:
            if not messagebox.askyesno("JARVIS", "A task is running. Stop it and close the window?"):
                return
            self.process.terminate()
        self.root.destroy()


def _display_argument(value: str) -> str:
    if len(value) > 100:
        return '"<task text>"'
    return f'"{value}"' if any(character.isspace() for character in value) else value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the JARVIS Coding Agent GUI")
    parser.add_argument("--workspace", default=str(Path.cwd()), help="initial project directory")
    args = parser.parse_args(argv)
    root = tk.Tk()
    JarvisGUI(root, args.workspace)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
