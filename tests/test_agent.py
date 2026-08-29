from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from jarvis_agent.agent import Agent
from jarvis_agent.config import Config
from jarvis_agent.policy import Policy
from jarvis_agent.tool_protocol import ToolRegistry
from jarvis_agent.tools import built_in_tools
from jarvis_agent.types import ModelResponse, ToolCall


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append((messages, tools))
        return next(self.responses)


class AgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name).resolve()
        self.config = Config("key", "model", "https://example.test/v1", root, max_turns=5)
        self.registry = ToolRegistry(
            built_in_tools(command_timeout=2, output_limit=1000),
            Policy(root, auto_approve=True),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_tool_result_is_returned_to_model_before_final_answer(self) -> None:
        client = FakeClient(
            [
                ModelResponse(tool_calls=[ToolCall("write-1", "write_file", {"path": "answer.txt", "content": "42"})]),
                ModelResponse(content="Created answer.txt and verified the write."),
            ]
        )
        result = Agent(self.config, client, self.registry).run("Create answer.txt")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.turns, 2)
        self.assertEqual(result.tool_calls, 1)
        second_messages = client.requests[1][0]
        self.assertEqual(second_messages[-1]["role"], "tool")
        self.assertEqual(second_messages[-1]["tool_call_id"], "write-1")
        self.assertEqual((self.config.workspace / "answer.txt").read_text(), "42")

    def test_max_turns_stops_endless_tool_loop(self) -> None:
        config = replace(self.config, max_turns=2)
        client = FakeClient(
            [
                ModelResponse(tool_calls=[ToolCall("1", "list_files", {})]),
                ModelResponse(tool_calls=[ToolCall("2", "list_files", {})]),
            ]
        )
        result = Agent(config, client, self.registry).run("Keep looking")
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.stop_reason, "max_turns")

    def test_three_identical_tool_errors_stop_loop(self) -> None:
        client = FakeClient(
            [
                ModelResponse(tool_calls=[ToolCall(str(i), "missing_tool", {})]) for i in range(3)
            ]
        )
        result = Agent(self.config, client, self.registry).run("Use a missing tool")
        self.assertEqual(result.stop_reason, "repeated_tool_error")
        self.assertEqual(result.tool_calls, 3)

