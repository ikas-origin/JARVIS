import io
import unittest
from unittest.mock import patch

from jarvis_agent.terminal_ui import TerminalUI, _summarize_arguments


class TerminalUITests(unittest.TestCase):
    def test_plain_banner_contains_identity_and_runtime_status_without_ansi(self) -> None:
        output = io.StringIO()
        TerminalUI(color=False, stream=output).banner(
            version="1.1.0",
            workspace="C:/project",
            model="demo-model",
            branch="dev",
            session_id="abc123",
            approval="ask",
            tools=7,
            streaming=True,
            mode="REACT",
        )
        rendered = output.getvalue()
        self.assertIn("J A R V I S", rendered)
        self.assertIn("━━━━━━━━━━━━━━━━━━━━━━━", rendered)
        self.assertIn("▼", rendered)
        self.assertIn("mode REACT", rendered)
        self.assertIn("tools 7", rendered)
        self.assertNotIn("\033[", rendered)

    def test_colored_banner_renders_triangle_in_bright_cyan(self) -> None:
        class TTYBuffer(io.StringIO):
            def isatty(self) -> bool:
                return True

        output = TTYBuffer()
        with patch.dict("jarvis_agent.terminal_ui.os.environ", {}, clear=True):
            TerminalUI(color=True, stream=output).banner(
                version="1.1.0",
                workspace="C:/project",
                model="demo-model",
                branch="dev",
                session_id=None,
                approval="ask",
                tools=7,
                streaming=True,
                mode="REACT",
            )
        rendered = output.getvalue()
        self.assertIn("\033[96m\033[1m", rendered)
        self.assertIn("━━━━━━━━━━━━━━━━━━━━━━━", rendered)

    def test_tool_argument_summary_does_not_dump_file_contents(self) -> None:
        rendered = _summarize_arguments(
            {"path": "demo.py", "content": "secret-looking source text" * 20}
        )
        self.assertIn("demo.py", rendered)
        self.assertIn("chars", rendered)
        self.assertNotIn("secret-looking source text", rendered)
