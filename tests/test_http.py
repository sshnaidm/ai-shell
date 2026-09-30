"""Request/response contract checks; no network calls or credentials required."""

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import httpx

from ai_shell.backends.http import BackendError, run_http_module
from ai_shell.config import ModuleConfig


class EventStream(httpx.SyncByteStream):
    def __init__(self, events):
        self.events = events

    def __iter__(self):
        for event in self.events:
            yield f"data: {json.dumps(event)}\n\n".encode()


CLAUDE_EVENTS = [
    {"type": "message_start", "message": {"content": []}},
    {"type": "ping"},
    {
        "type": "content_block_delta",
        "delta": {"type": "thinking_delta", "thinking": "Private reasoning"},
    },
    {
        "type": "content_block_delta",
        "delta": {"type": "text_delta", "text": "Hello "},
    },
    {
        "type": "content_block_delta",
        "delta": {"type": "text_delta", "text": "world"},
    },
    {"type": "message_stop"},
]


class HttpModuleTests(unittest.TestCase):
    def run_mocked(self, module, events, *, status=200):
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(
                status,
                headers={"Content-Type": "text/event-stream"},
                stream=EventStream(events),
            )

        client = httpx.Client(transport=httpx.MockTransport(handle))
        output = io.StringIO()
        with (
            patch("ai_shell.backends.http.httpx.Client", return_value=client),
            patch("ai_shell.backends.http._vertex_token", return_value="test-token"),
            redirect_stdout(output),
        ):
            run_http_module(module, "My question")
        self.assertEqual(len(requests), 1)
        return requests[0], output.getvalue()

    def vertex(self, **settings):
        return ModuleConfig(
            "vertex_test", "vertex", {"project": "test-project", **settings}
        )

    def test_claude_model_infers_anthropic_and_global(self):
        request, output = self.run_mocked(
            self.vertex(model="claude-sonnet-5", max_tokens=8192), CLAUDE_EVENTS
        )
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            str(request.url),
            "https://aiplatform.googleapis.com/v1/projects/test-project"
            "/locations/global/publishers/anthropic/models/claude-sonnet-5:streamRawPredict",
        )
        self.assertEqual(request.headers["Authorization"], "Bearer test-token")
        self.assertNotIn("x-api-key", request.headers)
        self.assertNotIn("anthropic-version", request.headers)
        self.assertEqual(
            json.loads(request.content),
            {
                "anthropic_version": "vertex-2023-10-16",
                "messages": [{"role": "user", "content": "My question"}],
                "max_tokens": 8192,
                "stream": True,
            },
        )
        self.assertEqual(output, "Hello world\n")

    def test_explicit_anthropic_publisher_uses_claude_defaults(self):
        request, output = self.run_mocked(
            self.vertex(publisher="anthropic"), CLAUDE_EVENTS
        )
        self.assertIn("/publishers/anthropic/models/claude-sonnet-5:", str(request.url))
        self.assertEqual(json.loads(request.content)["max_tokens"], 4096)
        self.assertEqual(output, "Hello world\n")

    def test_claude_multi_region_hosts(self):
        for location in ("us", "eu"):
            with self.subTest(location=location):
                request, output = self.run_mocked(
                    self.vertex(publisher="anthropic", location=location), CLAUDE_EVENTS
                )
                self.assertEqual(
                    request.url.host, f"aiplatform.{location}.rep.googleapis.com"
                )
                self.assertIn(f"/locations/{location}/", request.url.path)
                self.assertEqual(output, "Hello world\n")

    def test_older_claude_regional_model_preserves_version_suffix(self):
        request, _ = self.run_mocked(
            self.vertex(model="claude-sonnet-4-5@20250929", location="us-east5"),
            CLAUDE_EVENTS,
        )
        self.assertEqual(request.url.host, "us-east5-aiplatform.googleapis.com")
        self.assertIn(
            "/publishers/anthropic/models/claude-sonnet-4-5@20250929:", request.url.path
        )

    def test_gemini_vertex_keeps_its_format_and_uses_updated_default(self):
        events = [{"candidates": [{"content": {"parts": [{"text": "Gemini answer"}]}}]}]
        for location, host in (
            (None, "us-central1-aiplatform.googleapis.com"),
            ("global", "aiplatform.googleapis.com"),
        ):
            with self.subTest(location=location):
                settings = {"location": location} if location else {}
                request, output = self.run_mocked(self.vertex(**settings), events)
                self.assertEqual(request.url.host, host)
                self.assertIn(
                    "/publishers/google/models/gemini-3.8-flash:", request.url.path
                )
                self.assertTrue(request.url.path.endswith(":streamGenerateContent"))
                self.assertEqual(request.url.params["alt"], "sse")
                self.assertEqual(
                    json.loads(request.content),
                    {
                        "contents": [
                            {"role": "user", "parts": [{"text": "My question"}]}
                        ]
                    },
                )
                self.assertEqual(output, "Gemini answer\n")

    def test_direct_anthropic_retains_api_key_and_model_in_body(self):
        module = ModuleConfig("direct", "anthropic", {"api_key": "test-key"})
        request, output = self.run_mocked(module, CLAUDE_EVENTS)
        self.assertEqual(str(request.url), "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.headers["x-api-key"], "test-key")
        self.assertEqual(request.headers["anthropic-version"], "2023-06-01")
        body = json.loads(request.content)
        self.assertEqual(body["model"], "claude-sonnet-5")
        self.assertNotIn("anthropic_version", body)
        self.assertEqual(output, "Hello world\n")

    def test_anthropic_stream_error_is_reported_even_on_http_success(self):
        with self.assertRaisesRegex(BackendError, "Anthropic stream error: Overloaded"):
            self.run_mocked(
                self.vertex(model="claude-sonnet-5"),
                [
                    {
                        "type": "error",
                        "error": {"type": "overloaded_error", "message": "Overloaded"},
                    }
                ],
            )

    def test_vertex_http_error_is_reported(self):
        with self.assertRaisesRegex(BackendError, "HTTP 403"):
            self.run_mocked(self.vertex(model="claude-sonnet-5"), [], status=403)

    def test_invalid_vertex_settings_fail_before_authentication(self):
        for data, message in (
            (
                {"project": "test", "publisher": "unsupported"},
                "unsupported Vertex publisher",
            ),
            ({"model": "claude-sonnet-5"}, "needs `project`"),
        ):
            with self.subTest(data=data):
                with patch("ai_shell.backends.http._vertex_token") as token:
                    with self.assertRaisesRegex(BackendError, message):
                        run_http_module(
                            ModuleConfig("invalid", "vertex", data), "Question"
                        )
                    token.assert_not_called()


if __name__ == "__main__":
    unittest.main()
