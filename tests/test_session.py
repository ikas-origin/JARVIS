from pathlib import Path
import tempfile
import unittest

from jarvis_agent.errors import ConfigurationError
from jarvis_agent.session import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_round_trip_and_latest_are_workspace_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace_a = root / "a"
            workspace_b = root / "b"
            workspace_a.mkdir()
            workspace_b.mkdir()
            store = SessionStore(root / "sessions")
            first = store.create(workspace_a)
            first.messages = [{"role": "user", "content": "task a"}]
            store.save(first)
            second = store.create(workspace_b)
            second.messages = [{"role": "user", "content": "task b"}]
            store.save(second)

            loaded = store.load(first.id, workspace=workspace_a)
            self.assertEqual(loaded.messages[0]["content"], "task a")
            self.assertEqual(store.latest(workspace_a).id, first.id)
            self.assertEqual(store.latest(workspace_b).id, second.id)

    def test_resume_rejects_different_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace_a = root / "a"
            workspace_b = root / "b"
            workspace_a.mkdir()
            workspace_b.mkdir()
            store = SessionStore(root / "sessions")
            session = store.create(workspace_a)
            store.save(session)
            with self.assertRaises(ConfigurationError):
                store.load(session.id, workspace=workspace_b)

    def test_invalid_id_is_rejected_before_path_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory))
            with self.assertRaises(ConfigurationError):
                store.load("../config")
