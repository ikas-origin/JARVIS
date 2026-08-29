import unittest

from jarvis_agent.errors import ModelResponseError
from jarvis_agent.model_client import parse_chat_completion


class ModelParserTests(unittest.TestCase):
    def test_parses_text_and_tool_call(self) -> None:
        response = parse_chat_completion(
            {
                "choices": [
                    {
                        "message": {
                            "content": "I will inspect it.",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"total_tokens": 12},
            }
        )
        self.assertEqual(response.content, "I will inspect it.")
        self.assertEqual(response.tool_calls[0].name, "read_file")
        self.assertEqual(response.tool_calls[0].arguments, {"path": "README.md"})

    def test_rejects_malformed_arguments(self) -> None:
        with self.assertRaises(ModelResponseError):
            parse_chat_completion(
                {
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {"id": "x", "function": {"name": "read_file", "arguments": "{"}}
                                ],
                            }
                        }
                    ]
                }
            )

    def test_rejects_empty_response(self) -> None:
        with self.assertRaises(ModelResponseError):
            parse_chat_completion({"choices": [{"message": {"content": None}}]})

