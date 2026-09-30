"""Output contracts across terminals, redirected streams, and providers."""

import io
import json
import os
import pty
import re
import select
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx

from ai_shell.backends.http import run_http_module
from ai_shell.config import ConfigError, ModuleConfig, load_config
from ai_shell.output import ColorMode, OutputConfig, OutputFormat, TerminalRenderer
from ai_shell.prompt import build_prompt

ANSWER = "## Summary\n\n**Use find.**\n\n```bash\nfind . -type f\n```\n"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


class OutputTests(unittest.TestCase):
    def test_auto_format_follows_stdout_terminal_status(self):
        class Tty(io.StringIO):
            def isatty(self):
                return True

        self.assertEqual(OutputConfig().resolve_format(Tty()), OutputFormat.terminal)
        self.assertEqual(
            OutputConfig().resolve_format(io.StringIO()), OutputFormat.markdown
        )

    def test_renderer_handles_markers_split_across_chunks_and_code_blank_lines(self):
        stream = io.StringIO()
        renderer = TerminalRenderer(stream, color=ColorMode.never)
        text = ANSWER.replace("find . -type f", "echo '**literal**'\n\necho done")
        for character in text:
            renderer.write(character)
        renderer.finish()
        rendered = stream.getvalue()
        self.assertIn("Summary", rendered)
        self.assertIn("Use find.", rendered)
        self.assertIn("echo '**literal**'", rendered)
        self.assertIn("echo done", rendered)
        self.assertNotIn("## Summary", rendered)
        self.assertNotIn("**Use find.**", rendered)
        self.assertNotIn("```", rendered)
        self.assertNotIn("\x1b", rendered)

    def test_renderer_flushes_completed_blocks_before_answer_ends(self):
        stream = io.StringIO()
        renderer = TerminalRenderer(stream, color=ColorMode.never)
        renderer.write("**First paragraph.**\n\n")
        self.assertIn("First paragraph.", stream.getvalue())
        renderer.write("```bash\necho partial")
        renderer.finish()
        self.assertIn("echo partial", stream.getvalue())
        self.assertNotIn("```", stream.getvalue())

    def test_force_color_overrides_no_color_and_never_disables_styles(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            for color, ansi_expected in (
                (ColorMode.always, True),
                (ColorMode.never, False),
            ):
                with self.subTest(color=color):
                    stream = io.StringIO()
                    renderer = TerminalRenderer(stream, color=color)
                    renderer.write("**Emphasis**\n\n")
                    renderer.finish()
                    self.assertEqual(
                        bool(ANSI.search(stream.getvalue())), ansi_expected
                    )

    def test_plain_instructions_preserve_context_and_can_be_disabled(self):
        prompt = build_prompt("My question", "My log", output_format=OutputFormat.plain)
        self.assertIn("Do not use Markdown", prompt)
        self.assertIn("My log", prompt)
        self.assertIn("My question", prompt)
        for format in (OutputFormat.plain, OutputFormat.terminal):
            self.assertEqual(
                build_prompt(
                    "Exact question",
                    None,
                    output_format=format,
                    prompt_instructions=False,
                ),
                "Exact question",
            )
        self.assertEqual(build_prompt("Exact question", None), "Exact question")

    def test_config_defaults_and_invalid_output_settings(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            basic = 'default = "test"\n[modules.test]\ntype = "codex"\n'
            path.write_text(basic)
            self.assertEqual(load_config(path).output.format, OutputFormat.auto)
            path.write_text(
                basic
                + '[output]\nformat = "plain"\ncolor = "never"\nprompt_instructions = false\n'
            )
            settings = load_config(path).output
            self.assertEqual(settings.format, OutputFormat.plain)
            self.assertEqual(settings.color, ColorMode.never)
            self.assertFalse(settings.prompt_instructions)
            for invalid in ('format = "invalid"', 'prompt_instructions = "false"'):
                path.write_text(basic + "[output]\n" + invalid + "\n")
                with self.assertRaises(ConfigError):
                    load_config(path)

    def test_http_stream_uses_terminal_renderer_without_raw_markers(self):
        # The model output is split inside Markdown markers and a code fence.
        events = [
            {"choices": [{"delta": {"content": ANSWER[:20]}}]},
            {"choices": [{"delta": {"content": ANSWER[20:]}}]},
        ]
        data = (
            "".join(f"data: {json.dumps(event)}\n\n" for event in events)
            + "data: [DONE]\n\n"
        )
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=data)
            )
        )
        stream = io.StringIO()
        renderer = TerminalRenderer(stream, color=ColorMode.never)
        with patch("ai_shell.backends.http.httpx.Client", return_value=client):
            run_http_module(
                ModuleConfig(
                    "test", "openai", {"api_key": "test", "model": "gpt-6-luna"}
                ),
                "Question",
                write=renderer.write,
            )
        renderer.finish()
        self.assertIn("find . -type f", stream.getvalue())
        self.assertNotIn("```", stream.getvalue())
        self.assertNotIn("**", stream.getvalue())


class OutputCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.prompt_file = self.root / "prompt.txt"
        stub = self.root / "codex"
        stub.write_text(
            f"#!{sys.executable}\n"
            "import pathlib, sys\n"
            f"pathlib.Path({str(self.prompt_file)!r}).write_text(sys.argv[-1])\n"
            "print('Codex diagnostic', file=sys.stderr)\n"
            f"print({ANSWER!r}, end='', flush=True)\n"
            "if '--fail' in sys.argv: sys.exit(7)\n"
        )
        stub.chmod(0o755)
        self.config = self.root / "config.toml"
        self.config.write_text(
            'default = "codex"\n[modules.codex]\ntype = "codex"\n'
            f"command = {json.dumps(str(stub))}\n"
        )

    def command(self, *options):
        return [
            sys.executable,
            "-m",
            "ai_shell.cli",
            "--config",
            str(self.config),
            *options,
            "Question",
        ]

    def test_redirected_auto_output_stays_raw_and_prompt_unchanged(self):
        result = subprocess.run(
            self.command(), input="", capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, ANSWER)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.prompt_file.read_text(), "Question")

    def test_terminal_format_override_renders_redirected_answer(self):
        result = subprocess.run(
            self.command("--format", "terminal", "--color", "never"),
            input="",
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("find . -type f", result.stdout)
        self.assertNotIn("```", result.stdout)
        self.assertNotIn("**", result.stdout)
        self.assertNotIn("\x1b", result.stdout)
        self.assertIn("Markdown renderer", self.prompt_file.read_text())

    def test_plain_flag_overrides_terminal_config_and_changes_prompt(self):
        with self.config.open("a") as file:
            file.write('[output]\nformat = "terminal"\ncolor = "always"\n')
        result = subprocess.run(
            self.command("--format", "plain"),
            input="",
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # Plain mode passes through the answer; the model may ignore its instructions.
        self.assertEqual(result.stdout, ANSWER)
        self.assertIn("Do not use Markdown", self.prompt_file.read_text())

    def test_rendered_failure_still_preserves_codex_diagnostics_and_exit_code(self):
        with self.config.open("a") as file:
            file.write('extra_args = ["--fail"]\n')
        result = subprocess.run(
            self.command("--format", "terminal", "--color", "never"),
            input="",
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 7)
        self.assertIn("Codex diagnostic", result.stderr)
        self.assertIn("exit code 7", result.stderr)
        self.assertNotIn("```", result.stdout)
        self.assertIn("find . -type f", result.stdout)

    def test_auto_formats_a_real_terminal(self):
        master, slave = pty.openpty()
        try:
            with subprocess.Popen(
                self.command(),
                stdin=subprocess.DEVNULL,
                stdout=slave,
                stderr=subprocess.PIPE,
                env={**os.environ, "TERM": "xterm-256color"},
            ) as process:
                os.close(slave)
                slave = None
                answer = bytearray()
                try:
                    while True:
                        readable, _, _ = select.select([master], [], [], 5)
                        self.assertTrue(readable, "No terminal output received")
                        try:
                            chunk = os.read(master, 65536)
                        except OSError as error:
                            if error.errno != 5:  # Linux PTY returns EIO at EOF.
                                raise
                            break
                        if not chunk:
                            break
                        answer.extend(chunk)
                    _, errors = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 0, errors)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()
            text = answer.decode()
            self.assertIn("find . -type f", text)
            self.assertNotIn("```", text)
            self.assertNotIn("## Summary", text)
            self.assertIn("Markdown renderer", self.prompt_file.read_text())
        finally:
            os.close(master)
            if slave is not None:
                os.close(slave)


if __name__ == "__main__":
    unittest.main()
