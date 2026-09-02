import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib import error, request

from jarvis_agent.config import Config
from jarvis_agent.types import ModelResponse, ToolCall
from jarvis_agent.web import JarvisWebServer, WebBusyError, WebRuntime


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)

    def complete(self, _messages, _tools, on_text_delta=None):
        response = next(self.responses)
        if on_text_delta and response.content:
            on_text_delta(response.content)
        return response


class BlockingClient:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def complete(self, _messages, _tools, on_text_delta=None):
        self.entered.set()
        self.release.wait(3)
        if on_text_delta:
            on_text_delta("Done")
        return ModelResponse(content="Done")


class WebRuntimeTests(unittest.TestCase):
    def config(self, root: Path) -> Config:
        return Config(
            "secret-key",
            "test-model",
            "https://example.test/v1",
            root,
            config_path=root / "config.json",
            max_turns=8,
            command_timeout=2,
        )

    def wait_for_terminal(self, runtime: WebRuntime, task_id: str) -> dict:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            task = runtime.task_snapshot(task_id)["task"]
            if task["status"] not in {"queued", "running", "waiting_approval"}:
                return task
            time.sleep(0.02)
        self.fail("Web task did not reach a terminal state")

    def wait_for_approval(self, runtime: WebRuntime, task_id: str, after: int = 0) -> tuple[str, int]:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            task = runtime.task_snapshot(task_id, after=after)["task"]
            for event_item in task["events"]:
                if event_item["type"] == "approval_required":
                    return event_item["data"]["approval_id"], task["last_seq"]
            after = task["last_seq"]
            time.sleep(0.02)
        self.fail("Web task did not request approval")

    def test_status_is_safe_and_identifies_local_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = WebRuntime(
                self.config(Path(directory)),
                save_session=False,
                client=FakeClient([ModelResponse(content="unused")]),
            )
            status = runtime.status()
        self.assertEqual(status["model"], "test-model")
        self.assertEqual(status["approval"], "ask in browser")
        self.assertEqual(status["tool_count"], 7)
        self.assertNotIn("secret-key", json.dumps(status))

    def test_only_one_workspace_task_runs_at_a_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = BlockingClient()
            runtime = WebRuntime(
                self.config(Path(directory)),
                auto_approve=True,
                save_session=False,
                client=client,
            )
            first = runtime.start_task("First task")
            self.assertTrue(client.entered.wait(2))
            with self.assertRaises(WebBusyError):
                runtime.start_task("Conflicting task")
            client.release.set()
            task = self.wait_for_terminal(runtime, first["task_id"])

        self.assertEqual(task["status"], "completed")
        event_types = [event_item["type"] for event_item in task["events"]]
        self.assertIn("assistant_delta", event_types)
        self.assertIn("task_finished", event_types)

    def test_browser_approvals_unblock_write_and_verify_actions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            responses = [
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            "write",
                            "write_file",
                            {"path": "answer.txt", "content": "42\n"},
                        )
                    ]
                ),
                ModelResponse(content="Written"),
                ModelResponse(
                    tool_calls=[
                        ToolCall(
                            "verify",
                            "run_command",
                            {"command": "python -c \"print('verified')\"", "purpose": "verify"},
                        )
                    ]
                ),
                ModelResponse(content="Created and verified answer.txt"),
            ]
            runtime = WebRuntime(
                self.config(root),
                auto_approve=False,
                save_session=False,
                client=FakeClient(responses),
            )
            started = runtime.start_task("Create answer.txt")
            task_id = started["task_id"]
            first_approval, first_seq = self.wait_for_approval(runtime, task_id)
            runtime.resolve_approval(first_approval, True)
            second_approval, _second_seq = self.wait_for_approval(runtime, task_id, first_seq)
            runtime.resolve_approval(second_approval, True)
            task = self.wait_for_terminal(runtime, task_id)

            self.assertEqual((root / "answer.txt").read_text(encoding="utf-8"), "42\n")
            self.assertEqual(task["result"]["verification_status"], "passed")
            self.assertEqual(task["status"], "completed")


class WebHttpTests(unittest.TestCase):
    def test_static_page_and_token_protected_api(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = Config(
                "key",
                "model",
                "https://example.test/v1",
                root,
                config_path=root / "config.json",
            )
            runtime = WebRuntime(
                config,
                auto_approve=True,
                save_session=False,
                client=FakeClient([ModelResponse(content="Done")]),
            )
            server = JarvisWebServer(("127.0.0.1", 0), runtime, "test-token")
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                with request.urlopen(base_url + "/", timeout=2) as response:
                    page = response.read().decode("utf-8")
                    self.assertIn("JARVIS Web Console", page)
                    self.assertIn("Content-Security-Policy", response.headers)

                with self.assertRaises(error.HTTPError) as unauthorized:
                    request.urlopen(base_url + "/api/status", timeout=2)
                self.assertEqual(unauthorized.exception.code, 401)

                status_request = request.Request(
                    base_url + "/api/status",
                    headers={"X-JARVIS-Token": "test-token"},
                )
                with request.urlopen(status_request, timeout=2) as response:
                    payload = json.loads(response.read())
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["workspace"], str(root.resolve()))
            finally:
                server.shutdown()
                server.server_close()
                worker.join(2)


if __name__ == "__main__":
    unittest.main()
