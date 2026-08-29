import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jarvis_agent.config import Config
from jarvis_agent.errors import ConfigurationError


class ConfigTests(unittest.TestCase):
    def test_doctor_does_not_expose_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"JARVIS_API_KEY": "super-secret", "JARVIS_MODEL": "test-model"},
            clear=True,
        ):
            result = Config.from_env(workspace=directory).doctor()

        self.assertTrue(result["ok"])
        self.assertNotIn("super-secret", str(result))
        self.assertEqual(result["auth"], {"available": True, "source": "env"})

    def test_validate_reports_missing_variables(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            config = Config.from_env(workspace=directory)
            with self.assertRaises(ConfigurationError) as raised:
                config.validate_for_run()

        self.assertIn("JARVIS_API_KEY", str(raised.exception))
        self.assertIn("JARVIS_MODEL", str(raised.exception))

    def test_workspace_is_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Config.from_env(workspace=directory)
            self.assertEqual(config.workspace, Path(directory).resolve())

