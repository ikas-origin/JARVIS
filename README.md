# JARVIS

JARVIS is a lightweight Coding Agent: it works with an LLM to inspect a local
codebase, edit files, run commands, observe the results, and continue until the
programming task is complete.

This project implements its own agent loop, conversation/context management,
tool definitions and local execution, model response parsing, termination
rules, and error handling. It does not use an agent framework or server-hosted
code execution.

## Status

The first milestone targets a small, reliable CLI and an OpenAI-compatible Chat
Completions endpoint with native tool calling.

## Requirements

- Python 3.11+
- An OpenAI-compatible API endpoint that supports tool calling

## Install for development

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Configure the model through environment variables:

```powershell
$env:JARVIS_API_KEY = "your-api-key"
$env:JARVIS_MODEL = "your-model-name"
$env:JARVIS_BASE_URL = "https://api.openai.com/v1"
```

Never commit API keys. JARVIS does not accept a key as a CLI argument, so it
cannot accidentally leak through shell history or process listings.

For a persistent setup that survives terminal restarts, run:

```powershell
jarvis configure
```

The command hides key input and stores the settings in
`~/.jarvis/config.json`, outside the Git repository. Environment variables
still take precedence, so they can temporarily override saved settings. Set
`JARVIS_CONFIG` only when you intentionally want a different config-file path.

## Usage

```powershell
jarvis doctor
jarvis --json doctor
jarvis --yes "Inspect this project, fix the failing tests, and run them again."
jarvis --workspace D:\path\to\project --yes "Add tests for the parser."
jarvis --yes  # interactive session
```

JARVIS saves each conversation outside the repository under
`~/.jarvis/sessions`. Resume the newest session for the same workspace or an
exact session ID:

```powershell
jarvis sessions
jarvis --json sessions
jarvis --continue --yes "Now add the missing edge-case tests."
jarvis --resume SESSION_ID --yes "Continue the previous task."
jarvis --no-session --yes "Run a one-off task without saving history."
```

Human-readable mode streams assistant text as it arrives while continuing to
show tool start/result events. Use `--no-stream` when debugging a provider that
does not implement OpenAI-compatible SSE correctly. `--json` is deliberately
non-streaming so stdout remains exactly one JSON object.

Without `--yes`, read-only tools execute automatically, while file writes and
commands require interactive confirmation. Commands that match JARVIS's
high-risk denylist are refused even with `--yes`.

## CLI output contract

Human-readable output is the default. With `--json`, stdout contains one JSON
object only; progress is suppressed and errors use this shape:

```json
{"ok": false, "error": {"type": "configuration_error", "message": "..."}}
```

Successful `doctor` output reports whether credentials exist, never their
value. A completed task returns `ok`, `status`, `answer`, `turns`, and
`tool_calls`, plus accumulated provider usage and elapsed time.

The built-in Coding Agent tools are `list_files`, `search_text`, `read_file`,
`write_file`, `edit_file`, and `run_command`. `search_text` supports literal or
regular-expression matching, file globs, case control, and a bounded result
count without requiring an external `grep` or `rg` executable.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Safety boundary

All file tools resolve paths against one workspace and reject paths that escape
it, including traversal through symlinks. Common credential files and `.git`
metadata are not exposed to file tools. Command execution has a timeout,
bounded output, a sanitized child environment, workspace working directory,
and a conservative dangerous-command denylist. This is a guardrail, not an OS
sandbox: shell commands can still access resources allowed by your operating
system, so run JARVIS only on trusted tasks in a repository you can safely
modify.
