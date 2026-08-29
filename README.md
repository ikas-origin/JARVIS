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

## Usage

```powershell
jarvis doctor
jarvis --json doctor
jarvis --yes "Inspect this project, fix the failing tests, and run them again."
jarvis --workspace D:\path\to\project --yes "Add tests for the parser."
jarvis --yes  # interactive session
```

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
`tool_calls`.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Safety boundary

All file tools resolve paths against one workspace and reject paths that escape
it, including traversal through symlinks. Command execution has a timeout,
bounded output, workspace working directory, and a conservative dangerous
command denylist. This is a guardrail, not an OS sandbox: run JARVIS only in a
repository you can safely modify.

