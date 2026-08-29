import json
from pathlib import Path
import tempfile
import unittest

from jarvis_agent.errors import ConfigurationError
from jarvis_agent.spec import SpecStore, phase_prompt


class SpecStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.store = SpecStore(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_create_persist_and_find_active_spec(self) -> None:
        state = self.store.create("health-agent", "Build a safe health consultation prototype")
        loaded = self.store.load("health-agent")
        self.assertEqual(loaded.name, state.name)
        self.assertEqual(loaded.phase, "requirements")
        self.assertEqual(self.store.active().name, "health-agent")  # type: ignore[union-attr]
        self.assertTrue((self.root / ".jarvis/specs/health-agent/state.json").is_file())

    def test_invalid_or_parallel_spec_is_rejected(self) -> None:
        with self.assertRaises(ConfigurationError):
            self.store.create("../escape", "bad")
        self.store.create("first", "first goal")
        with self.assertRaises(ConfigurationError):
            self.store.create("second", "second goal")

    def test_tampered_state_name_is_rejected(self) -> None:
        state = self.store.create("safe", "safe goal")
        path = self.store.directory(state.name) / "state.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["name"] = "../escape"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ConfigurationError):
            self.store.load("safe")

    def test_approval_state_machine_requires_artifacts(self) -> None:
        state = self.store.create("feature", "Build one feature")
        with self.assertRaises(ConfigurationError):
            self.store.approve(state)

        self.store.artifact_path(state, "requirements").write_text("# Requirements\n", encoding="utf-8")
        self.assertEqual(self.store.approve(state), "design")
        self.assertEqual(state.approvals, ["requirements"])

        self.store.artifact_path(state, "design").write_text("# Design\n", encoding="utf-8")
        self.assertEqual(self.store.approve(state), "tasks")
        self.store.artifact_path(state, "tasks").write_text(
            "- [ ] T1 create code\n- [x] T2 existing setup\n", encoding="utf-8"
        )
        self.assertEqual(self.store.approve(state), "implementing")
        self.assertEqual(self.store.next_task(state), "T1 create code")
        self.assertFalse(self.store.all_tasks_complete(state))

        self.store.artifact_path(state, "tasks").write_text(
            "- [x] T1 create code\n- [x] T2 existing setup\n", encoding="utf-8"
        )
        self.assertTrue(self.store.all_tasks_complete(state))

    def test_verification_requires_exact_pass_status(self) -> None:
        state = self.store.create("verify", "Verify a feature")
        path = self.store.artifact_path(state, "verification")
        path.write_text("Status: FAIL\n", encoding="utf-8")
        self.assertFalse(self.store.verification_passed(state))
        path.write_text("# Evidence\n\nStatus: PASS\n", encoding="utf-8")
        self.assertTrue(self.store.verification_passed(state))

    def test_failed_verification_can_create_a_remediation_task(self) -> None:
        state = self.store.create("remediate", "Build and verify")
        self.store.artifact_path(state, "tasks").write_text(
            "- [x] T1 implement feature\n", encoding="utf-8"
        )
        first = self.store.add_verification_fix_task(state)
        second = self.store.add_verification_fix_task(state)
        self.assertTrue(first.startswith("TV1 "))
        self.assertTrue(second.startswith("TV2 "))
        self.assertEqual(self.store.next_task(state), first)

    def test_phase_prompt_names_exact_workspace_artifact(self) -> None:
        state = self.store.create("demo", "Create a parser")
        prompt = phase_prompt(state, "requirements")
        self.assertIn(".jarvis/specs/demo/requirements.md", prompt)
        self.assertIn("do not run commands", prompt.lower())
