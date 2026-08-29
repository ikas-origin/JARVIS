import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from jarvis_agent.cli import main


class CliTests(unittest.TestCase):
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
