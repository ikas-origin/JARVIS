import json
import unittest
from unittest.mock import patch
from urllib import error

from jarvis_agent.errors import ModelAuthenticationError, ModelError, ModelResponseError
from jarvis_agent.model_client import (
    OpenAICompatibleClient,
    parse_chat_completion,
    parse_chat_completion_stream,
)


class ModelParserTests(unittest.TestCase):
    def test_rate_limit_retries_with_bounded_exponential_backoff(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, _type, _value, _traceback):
                return False

            def read(self):
                return b'{"choices":[{"message":{"content":"recovered"}}]}'

        failures = [
            error.HTTPError("https://example.test", 429, "limited", {}, None),
            error.HTTPError("https://example.test", 429, "limited", {}, None),
            Response(),
        ]
        client = OpenAICompatibleClient(
            api_key="key",
            model="model",
            base_url="https://example.test/v1",
            max_retries=2,
        )
        with (
            patch("jarvis_agent.model_client.request.urlopen", side_effect=failures) as opener,
            patch("jarvis_agent.model_client.random.uniform", return_value=0),
            patch("jarvis_agent.model_client.time.sleep") as sleeper,
        ):
            response = client.complete([], [])

        self.assertEqual(response.content, "recovered")
        self.assertEqual(opener.call_count, 3)
        self.assertEqual([call.args[0] for call in sleeper.call_args_list], [1, 2])

    def test_authentication_failure_is_not_retried(self) -> None:
        client = OpenAICompatibleClient(
            api_key="key",
            model="model",
            base_url="https://example.test/v1",
            max_retries=5,
        )
        failure = error.HTTPError("https://example.test", 401, "unauthorized", {}, None)
        with patch("jarvis_agent.model_client.request.urlopen", side_effect=failure) as opener:
            with self.assertRaises(ModelAuthenticationError) as raised:
                client.complete([], [])
        self.assertEqual(getattr(raised.exception, "code", None), "authentication_error")
        self.assertEqual(opener.call_count, 1)

    def test_network_timeout_exhausts_only_the_configured_attempts(self) -> None:
        client = OpenAICompatibleClient(
            api_key="key",
            model="model",
            base_url="https://example.test/v1",
            timeout=0.01,
            max_retries=2,
        )
        with (
            patch(
                "jarvis_agent.model_client.request.urlopen",
                side_effect=TimeoutError("stalled socket"),
            ) as opener,
            patch("jarvis_agent.model_client.random.uniform", return_value=0),
            patch("jarvis_agent.model_client.time.sleep") as sleeper,
        ):
            with self.assertRaisesRegex(ModelError, "network error"):
                client.complete([], [])

        self.assertEqual(opener.call_count, 3)
        self.assertTrue(all(call.kwargs["timeout"] == 0.01 for call in opener.call_args_list))
        self.assertEqual([call.args[0] for call in sleeper.call_args_list], [1, 2])

    def test_malformed_response_shapes_are_normalized_to_model_errors(self) -> None:
        malformed = [
            {"choices": [{"message": []}]},
            {"choices": [{"message": {"content": 0}}]},
            {"choices": [{"message": {"content": "x", "tool_calls": 7}}]},
            {"choices": [{"message": {"content": "x"}}], "usage": []},
            {"choices": [{"message": {"content": "x"}, "finish_reason": 9}]},
        ]
        for payload in malformed:
            with self.subTest(payload=payload), self.assertRaises(ModelResponseError):
                parse_chat_completion(payload)

    def test_duplicate_tool_call_ids_are_rejected(self) -> None:
        with self.assertRaisesRegex(ModelResponseError, "duplicate tool call id"):
            parse_chat_completion(
                {
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {"id": "same", "function": {"name": "a", "arguments": "{}"}},
                                    {"id": "same", "function": {"name": "b", "arguments": "{}"}},
                                ],
                            }
                        }
                    ]
                }
            )

    def test_complete_sends_non_streaming_request_without_callback(self) -> None:
        requests = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, _type, _value, _traceback):
                return False

            def read(self):
                return b'{"choices":[{"message":{"content":"Done"}}]}'

        def open_request(http_request, *, timeout):
            requests.append((json.loads(http_request.data), timeout))
            return Response()

        client = OpenAICompatibleClient(
            api_key="key",
            model="model",
            base_url="https://example.test/v1",
        )
        with patch("jarvis_agent.model_client.request.urlopen", side_effect=open_request):
            response = client.complete([], [], None)

        self.assertEqual(response.content, "Done")
        self.assertFalse(requests[0][0]["stream"])
        self.assertNotIn("stream_options", requests[0][0])

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

    def test_stream_accumulates_fragmented_tool_call_id(self) -> None:
        lines = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-","function":{"name":"list_"}}]}}]}\n',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"1","function":{"name":"files","arguments":"{}"}}]}}]}\n',
            b"data: [DONE]\n",
        ]
        response = parse_chat_completion_stream(lines, lambda _text: None)
        self.assertEqual(response.tool_calls[0].id, "call-1")
        self.assertEqual(response.tool_calls[0].name, "list_files")

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
