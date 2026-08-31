import sys
import unittest

from jarvis_agent.gui import build_cli_command


class GuiCommandTests(unittest.TestCase):
    def test_builds_safe_argument_list_without_shell(self) -> None:
        command = build_cli_command(
            python=sys.executable,
            workspace=r"D:\Project With Spaces",
            task="fix tests; do not touch docs",
            max_turns=12,
            auto_approve=True,
            continue_session=True,
        )
        self.assertEqual(command[0:3], [sys.executable, "-m", "jarvis_agent"])
        self.assertIn(r"D:\Project With Spaces", command)
        self.assertIn("--yes", command)
        self.assertIn("--continue", command)
        self.assertEqual(command[-1], "fix tests; do not touch docs")

    def test_optional_flags_are_omitted(self) -> None:
        command = build_cli_command(
            python="python",
            workspace="project",
            task="inspect",
            max_turns=3,
            auto_approve=False,
            continue_session=False,
        )
        self.assertNotIn("--yes", command)

    def test_remote_consent_flag_is_explicit(self) -> None:
        command = build_cli_command(
            python=sys.executable,
            workspace="C:/demo",
            task="inspect",
            max_turns=20,
            auto_approve=False,
            continue_session=False,
            allow_remote=True,
        )
        self.assertIn("--allow-remote", command)
        self.assertNotIn("--continue", command)
