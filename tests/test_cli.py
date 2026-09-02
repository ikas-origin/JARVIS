import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from jarvis_agent.cli import (
    _git_branch,
    _handle_interactive_command,
    _interactive,
    _require_remote_consent,
    main,
)
from jarvis_agent.config import Config
from jarvis_agent.errors import ModelError
from jarvis_agent.session import SessionStore
from jarvis_agent.spec import SpecStore
from jarvis_agent.types import ModelResponse


class CliTests(unittest.TestCase):
    def test_interactive_model_failure_reports_error_and_accepts_next_command(self) -> None:
        class FailingAgent:
            def __init__(self, workspace: str) -> None:
                self.config = Config.from_env(workspace=workspace)
                self.messages = [{"role": "system", "content": "system"}]
                self.tools = type("Tools", (), {"schemas": []})()

            def run(self, _task: str):
                raise ModelError("temporary gateway failure")

        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with (
                patch("builtins.input", side_effect=["do something", "/exit"]),
                redirect_stdout(output),
                redirect_stderr(output),
            ):
                exit_code = _interactive(
                    FailingAgent(directory),  # type: ignore[arg-type]
                    None,
                    SessionStore(Path(directory) / "sessions"),
                    None,
                    auto_approve=False,
                    streaming=False,
                )
        self.assertEqual(exit_code, 0)
        self.assertIn("temporary gateway failure", output.getvalue())

    def test_json_and_no_stream_disable_model_streaming(self) -> None:
        class TrackingClient:
            def __init__(self) -> None:
                self.callbacks = []

            def complete(self, _messages, _tools, on_text_delta=None):
                self.callbacks.append(on_text_delta)
                return ModelResponse(content="Done")

        for flag in ("--json", "--no-stream"):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as directory:
                client = TrackingClient()
                output = io.StringIO()
                environment = {
                    "JARVIS_API_KEY": "key",
                    "JARVIS_MODEL": "model",
                    "JARVIS_BASE_URL": "http://127.0.0.1:8000/v1",
                    "JARVIS_CONFIG": os.path.join(directory, "config.json"),
                }
                with (
                    patch.dict(os.environ, environment, clear=True),
                    patch("jarvis_agent.cli.OpenAICompatibleClient", return_value=client),
                    redirect_stdout(output),
                    redirect_stderr(output),
                ):
                    exit_code = main(
                        ["--workspace", directory, flag, "--no-session", "report status"]
                    )
                self.assertEqual(exit_code, 0)
                self.assertEqual(client.callbacks, [None])

    def test_remote_model_requires_explicit_data_consent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Config("key", "model", "https://api.example.test/v1", Path(directory))
            with self.assertRaisesRegex(Exception, "--allow-remote"):
                _require_remote_consent(config, False)
            _require_remote_consent(config, True)

    def test_local_model_does_not_require_remote_consent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Config("key", "model", "http://127.0.0.1:11434/v1", Path(directory))
            _require_remote_consent(config, False)

    def test_json_doctor_has_stable_shape_and_no_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "JARVIS_API_KEY": "secret-value",
                "JARVIS_MODEL": "demo-model",
                "JARVIS_CONFIG": os.path.join(directory, "config.json"),
            },
            clear=True,
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--workspace", directory, "--json", "doctor"])
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["auth"], {"available": True, "source": "env"})
        self.assertNotIn("secret-value", output.getvalue())

    def test_json_interactive_mode_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"JARVIS_API_KEY": "key", "JARVIS_MODEL": "model"},
            clear=True,
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--workspace", directory, "--json"])
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["error"]["type"], "jarvis_error")

    def test_configure_stores_key_without_printing_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = os.path.join(directory, "config.json")
            with (
                patch.dict(os.environ, {"JARVIS_CONFIG": config_path}, clear=True),
                patch("jarvis_agent.cli.getpass", return_value="hidden-key"),
                patch("builtins.input", side_effect=["demo-model", "https://api.example.test/v1"]),
            ):
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = main(["--workspace", directory, "configure"])
            self.assertEqual(exit_code, 0)
            self.assertNotIn("hidden-key", output.getvalue())
            with open(config_path, encoding="utf-8") as saved:
                payload = json.load(saved)
            self.assertEqual(payload["api_key"], "hidden-key")
            self.assertEqual(payload["model"], "demo-model")

    def test_json_sessions_is_available_without_model_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"JARVIS_CONFIG": os.path.join(directory, "config.json")},
            clear=True,
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--workspace", directory, "--json", "sessions"])
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload, {"ok": True, "sessions": []})

    def test_git_branch_returns_none_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(_git_branch(Config.from_env(workspace=directory).workspace))

    def test_interactive_clear_resets_context(self) -> None:
        class FakeAgent:
            def __init__(self, workspace: str) -> None:
                self.config = Config.from_env(workspace=workspace)
                self.messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]

            def reset_context(self) -> None:
                self.messages = self.messages[:1]

        with tempfile.TemporaryDirectory() as directory:
            agent = FakeAgent(directory)
            output = io.StringIO()
            with redirect_stdout(output):
                should_exit = _handle_interactive_command(
                    "/clear",
                    agent,  # type: ignore[arg-type]
                    None,
                    SessionStore(Config.from_env(workspace=directory).config_path.parent / "sessions"),
                    auto_approve=False,
                    streaming=True,
                )
        self.assertFalse(should_exit)
        self.assertEqual(len(agent.messages), 1)
        self.assertIn("context cleared", output.getvalue())

    def test_spec_help_is_available_inside_interactive_commands(self) -> None:
        class FakeAgent:
            def __init__(self, workspace: str) -> None:
                self.config = Config.from_env(workspace=workspace)

        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stdout(output):
                should_exit = _handle_interactive_command(
                    "/spec help",
                    FakeAgent(directory),  # type: ignore[arg-type]
                    None,
                    SessionStore(Path(directory) / "sessions"),
                    auto_approve=False,
                    streaming=True,
                )
        self.assertFalse(should_exit)
        self.assertIn("/spec implement", output.getvalue())

    def test_active_spec_blocks_free_form_interactive_task(self) -> None:
        class FakeAgent:
            def __init__(self, workspace: str) -> None:
                self.config = Config.from_env(workspace=workspace)
                self.messages = [{"role": "system", "content": "system"}]
                self.run_count = 0

            def run(self, _task: str):
                self.run_count += 1
                raise AssertionError("free-form task must not run while a spec is active")

        with tempfile.TemporaryDirectory() as directory:
            SpecStore(Path(directory)).create("active", "Build a feature")
            agent = FakeAgent(directory)
            output = io.StringIO()
            with patch("builtins.input", side_effect=["change arbitrary code", "/exit"]), redirect_stdout(output):
                exit_code = _interactive(
                    agent,  # type: ignore[arg-type]
                    None,
                    SessionStore(Path(directory) / "sessions"),
                    None,
                    auto_approve=False,
                    streaming=True,
                )
        self.assertEqual(exit_code, 0)
        self.assertEqual(agent.run_count, 0)
        self.assertIn("Spec 'active' is active", output.getvalue())
