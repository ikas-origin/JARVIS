import os
from pathlib import Path
import tempfile
import unittest

from jarvis_agent.policy import Policy
from jarvis_agent.tool_protocol import ToolRegistry
from jarvis_agent.tools import built_in_tools


class ToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.registry = ToolRegistry(
            built_in_tools(command_timeout=2, output_limit=1000),
            Policy(self.root, auto_approve=True),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_write_read_and_edit_file(self) -> None:
        written = self.registry.execute("write_file", {"path": "src/hello.py", "content": "x = 1\n"})
        self.assertTrue(written.ok)
        read = self.registry.execute("read_file", {"path": "src/hello.py"})
        self.assertTrue(read.ok)
        self.assertIn("1 | x = 1", read.content)
        edited = self.registry.execute(
            "edit_file", {"path": "src/hello.py", "old_text": "x = 1", "new_text": "x = 2"}
        )
        self.assertTrue(edited.ok)
        self.assertEqual((self.root / "src/hello.py").read_text(), "x = 2\n")

    def test_path_traversal_is_rejected(self) -> None:
        result = self.registry.execute("read_file", {"path": "../secret.txt"})
        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["error_type"], "policy_error")

    def test_read_files_batches_known_files_with_metadata(self) -> None:
        (self.root / "one.py").write_text("first = 1\n", encoding="utf-8")
        (self.root / "two.py").write_text("second = 2\n", encoding="utf-8")
        result = self.registry.execute(
            "read_files", {"paths": ["one.py", "two.py"], "limit": 20}
        )
        self.assertTrue(result.ok, result.content)
        self.assertIn("===== one.py =====", result.content)
        self.assertIn("1 | first = 1", result.content)
        self.assertIn("===== two.py =====", result.content)
        self.assertEqual(result.metadata["file_count"], 2)
        self.assertEqual([item["path"] for item in result.metadata["files"]], ["one.py", "two.py"])

    def test_read_files_rejects_invalid_or_sensitive_batches(self) -> None:
        (self.root / "safe.txt").write_text("safe", encoding="utf-8")
        (self.root / ".env").write_text("SECRET=value", encoding="utf-8")
        duplicate = self.registry.execute("read_files", {"paths": ["safe.txt", "safe.txt"]})
        sensitive = self.registry.execute("read_files", {"paths": ["safe.txt", ".env"]})
        oversized = self.registry.execute(
            "read_files", {"paths": [f"file-{index}.txt" for index in range(9)]}
        )
        self.assertFalse(duplicate.ok)
        self.assertFalse(sensitive.ok)
        self.assertEqual(sensitive.metadata["error_type"], "policy_error")
        self.assertFalse(oversized.ok)

    def test_sensitive_files_and_git_metadata_are_refused(self) -> None:
        (self.root / ".env").write_text("TOKEN=secret", encoding="utf-8")
        env_result = self.registry.execute("read_file", {"path": ".env"})
        git_result = self.registry.execute("write_file", {"path": ".git/config", "content": "bad"})
        self.assertFalse(env_result.ok)
        self.assertFalse(git_result.ok)
        self.assertEqual(env_result.metadata["error_type"], "policy_error")

    def test_internal_spec_state_is_hidden_from_model_tools(self) -> None:
        state = self.root / ".jarvis" / "specs" / "demo" / "state.json"
        state.parent.mkdir(parents=True)
        state.write_text('{"phase":"requirements"}', encoding="utf-8")
        read = self.registry.execute(
            "read_file", {"path": ".jarvis/specs/demo/state.json"}
        )
        listed = self.registry.execute("list_files", {})
        self.assertFalse(read.ok)
        self.assertEqual(read.metadata["error_type"], "policy_error")
        self.assertNotIn("state.json", listed.content)

    def test_edit_requires_unique_match(self) -> None:
        (self.root / "same.txt").write_text("same same", encoding="utf-8")
        result = self.registry.execute(
            "edit_file", {"path": "same.txt", "old_text": "same", "new_text": "new"}
        )
        self.assertFalse(result.ok)
        self.assertIn("2 matches", result.content)

    def test_unknown_and_invalid_tool_calls_are_errors(self) -> None:
        self.assertFalse(self.registry.execute("missing", {}).ok)
        result = self.registry.execute("read_file", {"path": "x", "extra": True})
        self.assertFalse(result.ok)
        self.assertIn("Unexpected argument", result.content)

    def test_search_text_returns_paths_lines_and_honors_limit(self) -> None:
        (self.root / "first.py").write_text("Alpha\nneedle here\n", encoding="utf-8")
        (self.root / "second.py").write_text("NEEDLE again\n", encoding="utf-8")
        result = self.registry.execute(
            "search_text", {"query": "needle", "glob": "*.py", "limit": 1}
        )
        self.assertTrue(result.ok, result.content)
        self.assertIn("first.py:2: needle here", result.content)
        self.assertEqual(result.metadata["match_count"], 1)
        self.assertTrue(result.metadata["truncated"])

    def test_search_text_supports_regex_and_rejects_invalid_regex(self) -> None:
        (self.root / "value.txt").write_text("item_42\n", encoding="utf-8")
        result = self.registry.execute(
            "search_text", {"query": r"item_\d+", "regex": True, "case_sensitive": True}
        )
        self.assertTrue(result.ok)
        self.assertIn("value.txt:1", result.content)
        invalid = self.registry.execute("search_text", {"query": "[", "regex": True})
        self.assertFalse(invalid.ok)
        self.assertIn("Invalid regular expression", invalid.content)

    def test_command_runs_in_workspace_and_strips_secrets(self) -> None:
        old = os.environ.get("JARVIS_API_KEY")
        old_token = os.environ.get("DEMO_TOKEN")
        os.environ["JARVIS_API_KEY"] = "must-not-leak"
        os.environ["DEMO_TOKEN"] = "also-must-not-leak"
        try:
            command = (
                'python -c "import os; print(os.getcwd()); '
                "print(os.getenv('JARVIS_API_KEY')); print(os.getenv('DEMO_TOKEN'))\""
            )
            result = self.registry.execute("run_command", {"command": command})
        finally:
            if old is None:
                os.environ.pop("JARVIS_API_KEY", None)
            else:
                os.environ["JARVIS_API_KEY"] = old
            if old_token is None:
                os.environ.pop("DEMO_TOKEN", None)
            else:
                os.environ["DEMO_TOKEN"] = old_token
        self.assertTrue(result.ok, result.content)
        self.assertIn(str(self.root), result.content)
        self.assertNotIn("must-not-leak", result.content)
        self.assertNotIn("also-must-not-leak", result.content)

    def test_dangerous_command_is_refused_even_when_auto_approved(self) -> None:
        result = self.registry.execute("run_command", {"command": "git reset --hard"})
        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["error_type"], "policy_error")

    def test_spec_planning_restricts_writes_and_commands(self) -> None:
        spec_root = self.root / ".jarvis" / "specs" / "demo"
        self.registry.policy.restrict(write_roots=(spec_root,), commands_allowed=False)
        allowed = self.registry.execute(
            "write_file",
            {"path": ".jarvis/specs/demo/requirements.md", "content": "# Requirements\n"},
        )
        blocked_write = self.registry.execute(
            "write_file", {"path": "src/application.py", "content": "unsafe = True\n"}
        )
        blocked_command = self.registry.execute("run_command", {"command": "python --version"})
        self.assertTrue(allowed.ok, allowed.content)
        self.assertFalse(blocked_write.ok)
        self.assertEqual(blocked_write.metadata["error_type"], "policy_error")
        self.assertFalse(blocked_command.ok)
        self.assertEqual(blocked_command.metadata["error_type"], "policy_error")

        self.registry.policy.clear_restrictions()
        unrestricted = self.registry.execute(
            "write_file", {"path": "src/application.py", "content": "safe = True\n"}
        )
        self.assertTrue(unrestricted.ok, unrestricted.content)

    def test_spec_implementation_protects_approved_artifacts(self) -> None:
        requirements = self.root / ".jarvis" / "specs" / "demo" / "requirements.md"
        requirements.parent.mkdir(parents=True)
        requirements.write_text("approved\n", encoding="utf-8")
        self.registry.policy.restrict(
            write_roots=None,
            commands_allowed=True,
            denied_write_paths=(requirements,),
        )
        protected = self.registry.execute(
            "edit_file",
            {"path": ".jarvis/specs/demo/requirements.md", "old_text": "approved", "new_text": "changed"},
        )
        application = self.registry.execute(
            "write_file", {"path": "src/feature.py", "content": "enabled = True\n"}
        )
        self.assertFalse(protected.ok)
        self.assertEqual(protected.metadata["error_type"], "policy_error")
        self.assertEqual(requirements.read_text(encoding="utf-8"), "approved\n")
        self.assertTrue(application.ok, application.content)
