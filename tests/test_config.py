import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from jarvis_agent.config import Config, save_user_config
from jarvis_agent.errors import ConfigurationError


class ConfigTests(unittest.TestCase):
    def test_doctor_does_not_expose_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"JARVIS_API_KEY": "super-secret", "JARVIS_MODEL": "test-model"},
            clear=True,
        ):
            result = Config.from_env(
                workspace=directory, config_path=Path(directory) / "config.json"
            ).doctor()

        self.assertTrue(result["ok"])
        self.assertNotIn("super-secret", str(result))
        self.assertEqual(result["auth"], {"available": True, "source": "env"})

    def test_validate_reports_missing_variables(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            config = Config.from_env(
                workspace=directory, config_path=Path(directory) / "config.json"
            )
            with self.assertRaises(ConfigurationError) as raised:
                config.validate_for_run()

        self.assertIn("JARVIS_API_KEY", str(raised.exception))
        self.assertIn("JARVIS_MODEL", str(raised.exception))

    def test_workspace_is_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Config.from_env(
                workspace=directory, config_path=Path(directory) / "config.json"
            )
            self.assertEqual(config.workspace, Path(directory).resolve())

    def test_remote_base_url_requires_https(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "JARVIS_API_KEY": "key",
                "JARVIS_MODEL": "model",
                "JARVIS_BASE_URL": "http://models.example.test/v1",
            },
            clear=True,
        ):
            config = Config.from_env(
                workspace=directory, config_path=Path(directory) / "config.json"
            )
            with self.assertRaises(ConfigurationError):
                config.validate_for_run()
            self.assertFalse(config.doctor()["ok"])

    def test_local_http_model_server_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "JARVIS_API_KEY": "local-placeholder",
                "JARVIS_MODEL": "local-model",
                "JARVIS_BASE_URL": "http://127.0.0.1:11434/v1",
            },
            clear=True,
        ):
            Config.from_env(
                workspace=directory, config_path=Path(directory) / "config.json"
            ).validate_for_run()

    def test_user_config_persists_and_environment_wins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "user" / "config.json"
            save_user_config(
                api_key="saved-key",
                model="saved-model",
                base_url="https://saved.example/v1",
                path=config_path,
            )
            with patch.dict(os.environ, {}, clear=True):
                saved = Config.from_env(workspace=directory, config_path=config_path)
            self.assertEqual(saved.api_key, "saved-key")
            self.assertEqual(saved.model, "saved-model")
            self.assertEqual(saved.auth_source, "config")
            with patch.dict(
                os.environ,
                {"JARVIS_API_KEY": "env-key", "JARVIS_MODEL": "env-model"},
                clear=True,
            ):
                overridden = Config.from_env(workspace=directory, config_path=config_path)
            self.assertEqual(overridden.api_key, "env-key")
            self.assertEqual(overridden.model, "env-model")
            self.assertEqual(overridden.auth_source, "env")
