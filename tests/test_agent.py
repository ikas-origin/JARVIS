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

    def complete(self, messages, tools, on_text_delta=None):
        self.requests.append((messages, tools))
        response = next(self.responses)
        if on_text_delta and response.content:
            on_text_delta(response.content)
        return response


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
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            "verify-1",
                            "run_command",
                            {"command": "echo verified", "purpose": "verify"},
                        )
                    ]
                ),
                ModelResponse(content="Created answer.txt and verified the write.", usage={"total_tokens": 7}),
            ]
        )
        result = Agent(self.config, client, self.registry).run("Create answer.txt")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.turns, 3)
        self.assertEqual(result.tool_calls, 2)
        self.assertEqual(result.tool_usage, {"write_file": 1, "run_command": 1})
        self.assertEqual(result.verification_status, "passed")
        self.assertEqual(result.usage["total_tokens"], 7)
        self.assertGreaterEqual(result.elapsed_seconds, 0)
        second_messages = client.requests[1][0]
        self.assertEqual(second_messages[-1]["role"], "tool")
        self.assertEqual(second_messages[-1]["tool_call_id"], "write-1")
        self.assertEqual((self.config.workspace / "answer.txt").read_text(), "42")

    def test_checkpoint_records_each_message_boundary(self) -> None:
        snapshots = []
        client = FakeClient(
            [
                ModelResponse(tool_calls=[ToolCall("list-1", "list_files", {})]),
                ModelResponse(content="Done"),
            ]
        )
        Agent(
            self.config,
            client,
            self.registry,
            checkpoint=lambda messages: snapshots.append([dict(message) for message in messages]),
        ).run("Inspect files")
        roles = [[message["role"] for message in snapshot] for snapshot in snapshots]
        self.assertEqual(
            roles,
            [
                ["system"],
                ["system", "user"],
                ["system", "user", "assistant"],
                ["system", "user", "assistant", "tool"],
                ["system", "user", "assistant", "tool", "assistant"],
            ],
        )

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
        self.assertEqual(result.verification_status, "not_required")

    def test_write_requires_a_successful_command_before_completion(self) -> None:
        client = FakeClient(
            [
                ModelResponse(
                    tool_calls=[
                        ToolCall("write", "write_file", {"path": "answer.txt", "content": "42"})
                    ]
                ),
                ModelResponse(content="Done"),
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            "verify",
                            "run_command",
                            {"command": "echo verified", "purpose": "verify"},
                        )
                    ]
                ),
                ModelResponse(content="Created and verified answer.txt"),
            ]
        )
        events = []
        result = Agent(
            self.config,
            client,
            self.registry,
            on_event=lambda name, data: events.append((name, data)),
        ).run("Create answer.txt")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.turns, 4)
        self.assertEqual(result.tool_calls, 2)
        self.assertEqual(result.verification_status, "passed")
        self.assertIn("verification_required", [name for name, _ in events])
        self.assertIn("verification gate", client.requests[2][0][-1]["content"])

    def test_failed_command_does_not_satisfy_verification_gate(self) -> None:
        client = FakeClient(
            [
                ModelResponse(
                    tool_calls=[
                        ToolCall("write", "write_file", {"path": "answer.txt", "content": "42"})
                    ]
                ),
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            "failed",
                            "run_command",
                            {"command": "exit 1", "purpose": "verify"},
                        )
                    ]
                ),
                ModelResponse(content="Done despite the failure"),
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            "passed",
                            "run_command",
                            {"command": "echo fixed", "purpose": "verify"},
                        )
                    ]
                ),
                ModelResponse(content="Done and verified"),
            ]
        )
        result = Agent(self.config, client, self.registry).run("Create answer.txt")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.turns, 5)
        self.assertEqual(result.tool_calls, 3)
        self.assertEqual(result.verification_status, "passed")

    def test_successful_inspection_command_does_not_satisfy_verification_gate(self) -> None:
        client = FakeClient(
            [
                ModelResponse(
                    tool_calls=[
                        ToolCall("write", "write_file", {"path": "answer.txt", "content": "42"})
                    ]
                ),
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            "inspect",
                            "run_command",
                            {"command": "echo inspected", "purpose": "inspect"},
                        )
                    ]
                ),
                ModelResponse(content="Done after inspection only"),
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            "verify",
                            "run_command",
                            {"command": "echo verified", "purpose": "verify"},
                        )
                    ]
                ),
                ModelResponse(content="Done after verification"),
            ]
        )
        events = []
        result = Agent(
            self.config,
            client,
            self.registry,
            on_event=lambda name, data: events.append((name, data)),
        ).run("Create and verify answer.txt")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.turns, 5)
        self.assertEqual(result.verification_status, "passed")
        self.assertIn("verification_required", [name for name, _data in events])

    def test_project_context_is_injected_into_system_prompt(self) -> None:
        (self.config.workspace / "AGENTS.md").write_text("Always run unittest.", encoding="utf-8")
        client = FakeClient([ModelResponse(content="Understood")])
        agent = Agent(self.config, client, self.registry)
        self.assertIn("Always run unittest.", agent.messages[0]["content"])
