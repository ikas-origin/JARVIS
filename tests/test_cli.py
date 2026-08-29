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
            {"JARVIS_API_KEY": "secret-value", "JARVIS_MODEL": "demo-model"},
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

