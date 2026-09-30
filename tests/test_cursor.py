"""Cursor CLI routing, including the common `agent` name collision."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_shell.backends.cli import build_argv
from ai_shell.config import ModuleConfig


class CursorCliTests(unittest.TestCase):
    def run_with_agent(self, help_text):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            agent = root / "agent"
            agent.write_text(
                f"#!{sys.executable}\n"
                "import json, sys\n"
                "if '--help' in sys.argv:\n"
                f"    print({help_text!r})\n"
                "else:\n"
                "    print('CURSOR_SENT ' + json.dumps(sys.argv[1:]))\n"
            )
            agent.chmod(0o755)
            config = root / "config.toml"
            config.write_text(
                'default = "cursor"\n[modules.cursor]\ntype = "cursor"\n'
                'model = "test-model"\n'
            )
            env = os.environ.copy()
            env["PATH"] = f"{root}{os.pathsep}{env.get('PATH', '')}"
            source_root = str(Path(__file__).resolve().parents[1])
            env["PYTHONPATH"] = os.pathsep.join(
                filter(None, (source_root, env.get("PYTHONPATH")))
            )
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ai_shell.cli",
                    "--config",
                    str(config),
                    "One",
                    "question",
                ],
                cwd=root,
                env=env,
                input="",
                capture_output=True,
                text=True,
                timeout=10,
            )

    def test_cursor_agent_receives_noninteractive_prompt(self):
        result = self.run_with_agent("Start the Cursor Agent")
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = json.loads(result.stdout.removeprefix("CURSOR_SENT "))
        self.assertEqual(argv[0:2], ["-p", "One question"])
        self.assertIn("--output-format", argv)
        self.assertEqual(argv[argv.index("--output-format") + 1], "text")
        self.assertEqual(argv[-2:], ["--model", "test-model"])

    def test_other_agent_binary_is_rejected_before_prompt(self):
        result = self.run_with_agent("Grok Build TUI")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("CURSOR_SENT", result.stdout)
        self.assertIn("Cursor Agent", result.stderr)
        self.assertIn("`cursor` module", result.stderr)

    def test_explicit_command_is_respected(self):
        module = ModuleConfig("cursor", "cursor", {"command": "/tmp/cursor/agent"})
        self.assertEqual(
            build_argv(module, "Explain this"),
            ["/tmp/cursor/agent", "-p", "Explain this", "--output-format", "text"],
        )


if __name__ == "__main__":
    unittest.main()
