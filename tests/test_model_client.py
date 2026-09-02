import unittest

from jarvis_agent.errors import ModelResponseError
from jarvis_agent.model_client import parse_chat_completion, parse_chat_completion_stream


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

    def test_stream_accumulates_text_and_fragmented_tool_arguments(self) -> None:
        deltas = []
        lines = [
            b'data: {"choices":[{"delta":{"content":"Hello "},"finish_reason":null}]}\n',
            b'data: {"choices":[{"delta":{"content":"world"},"finish_reason":null}]}\n',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"read_","arguments":"{\\"pa"}}]},"finish_reason":null}]}\n',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"file","arguments":"th\\":\\"x.py\\"}"}}]},"finish_reason":"tool_calls"}]}\n',
            b'data: [DONE]\n',
        ]
        response = parse_chat_completion_stream(lines, deltas.append)
        self.assertEqual(response.content, "Hello world")
        self.assertEqual(deltas, ["Hello ", "world"])
        self.assertEqual(response.tool_calls[0].name, "read_file")
        self.assertEqual(response.tool_calls[0].arguments, {"path": "x.py"})

    def test_stream_requires_done_event(self) -> None:
        with self.assertRaises(ModelResponseError):
            parse_chat_completion_stream(
                [b'data: {"choices":[{"delta":{"content":"partial"}}]}\n'], lambda _text: None
            )

    def test_stream_wraps_invalid_json_as_model_response_error(self) -> None:
        with self.assertRaisesRegex(ModelResponseError, "invalid JSON"):
            parse_chat_completion_stream(
                [b"data: {not-json}\n", b"data: [DONE]\n"], lambda _text: None
            )

    def test_stream_rejects_invalid_tool_call_index_and_fragments(self) -> None:
        invalid_index = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":"bad"}]}}]}\n',
            b"data: [DONE]\n",
        ]
        with self.assertRaisesRegex(ModelResponseError, "index"):
            parse_chat_completion_stream(invalid_index, lambda _text: None)

        invalid_name = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":7}}]}}]}\n',
            b"data: [DONE]\n",
        ]
        with self.assertRaisesRegex(ModelResponseError, "tool name fragment"):
            parse_chat_completion_stream(invalid_name, lambda _text: None)
