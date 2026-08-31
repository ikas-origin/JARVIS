from pathlib import Path
import tempfile
import unittest

from jarvis_agent.project_context import load_project_context


class ProjectContextTests(unittest.TestCase):
    def test_loads_highest_priority_nonempty_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("use unittest", encoding="utf-8")
            (root / "JARVIS.md").write_text("use type hints", encoding="utf-8")
            context = load_project_context(root)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.path.name, "JARVIS.md")
        self.assertEqual(context.content, "use type hints")

    def test_ignores_empty_and_truncates_large_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "JARVIS.md").write_text("  ", encoding="utf-8")
            (root / "AGENTS.md").write_text("a" * 200, encoding="utf-8")
            context = load_project_context(root, max_chars=100)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.path.name, "AGENTS.md")
        self.assertTrue(context.truncated)
        self.assertIn("truncated AGENTS.md", context.content)

    def test_returns_none_without_context_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(load_project_context(Path(directory)))
