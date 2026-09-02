import json
import unittest

from jarvis_agent.context import trim_messages
from jarvis_agent.errors import AgentLimitError


class ContextTests(unittest.TestCase):
    def test_truncates_large_tool_output(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
            {"role": "tool", "tool_call_id": "1", "content": "x" * 10_000},
        ]
        result = trim_messages(messages, max_chars=20_000, per_tool_chars=100)
        self.assertIn("truncated", result[-1]["content"])
        self.assertLessEqual(len(result[-1]["content"]), 100)

    def test_drops_complete_old_tool_trajectory(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "old"}]},
            {"role": "tool", "tool_call_id": "old", "content": "old result" * 100},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "new"}]},
            {"role": "tool", "tool_call_id": "new", "content": "new result"},
        ]
        result = trim_messages(messages, max_chars=450, per_tool_chars=8_000)
        encoded = json.dumps(result)
        self.assertNotIn("old result", encoded)
        assistant_ids = [
            call["id"]
            for message in result
            for call in message.get("tool_calls", [])
        ]
        tool_ids = [message["tool_call_id"] for message in result if message["role"] == "tool"]
        self.assertEqual(assistant_ids, tool_ids)

    def test_raises_when_protected_messages_alone_exceed_budget(self) -> None:
        messages = [
            {"role": "system", "content": "s" * 100},
            {"role": "user", "content": "u" * 100},
        ]
        with self.assertRaises(AgentLimitError):
            trim_messages(messages, max_chars=50)

