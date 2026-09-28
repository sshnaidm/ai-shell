"""Exercise tmux context options through the installed CLI entry point."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class TmuxContextCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

        tmux = self.root / "tmux"
        tmux.write_text(
            f"#!{sys.executable}\n"
            "import sys\n"
            "args = sys.argv[1:]\n"
            "if args[0] == 'display-message':\n"
            "    print(4)\n"
            "elif args[0] == 'capture-pane':\n"
            "    history = [f'line {i}' for i in range(1, 9)]\n"
            "    visible = [f'line {i}' for i in range(9, 13)]\n"
            "    if '-S' in args:\n"
            "        start = int(args[args.index('-S') + 1])\n"
            "        history = history[start:]\n"
            "    else:\n"
            "        history = []\n"
            "    print('\\n'.join(history + visible) + '\\n')\n"
            "else:\n"
            "    sys.exit(f'Unexpected tmux command: {args}')\n"
        )
        tmux.chmod(0o755)

        provider = self.root / "provider"
        provider.write_text(
            f"#!{sys.executable}\n"
            "import json, sys\n"
            "print(json.dumps(sys.argv[-1]))\n"
        )
        provider.chmod(0o755)

        self.config = self.root / "config.toml"
        self.config.write_text(
            'default = "mock"\n[modules.mock]\ntype = "cli"\n'
            f"command = {json.dumps(str(provider))}\n"
        )

    def run_ai(self, *args):
        env = os.environ.copy()
        env["TMUX"] = "fake"
        env["PATH"] = os.pathsep.join((str(self.root), env.get("PATH", "")))
        source = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (source, env.get("PYTHONPATH"))))
        return subprocess.run(
            [sys.executable, "-m", "ai_shell.cli", "--config", str(self.config), *args],
            env=env, input="", capture_output=True, text=True, timeout=10,
        )

    def test_context_without_count_uses_visible_pane(self):
        result = self.run_ai("-c", "What happened?")
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = json.loads(result.stdout)
        self.assertIn("line 9\n", prompt)
        self.assertIn("line 12\n", prompt)
        self.assertNotIn("line 8\n", prompt)
        self.assertIn("My Question: What happened?", prompt)

    def test_context_screen_count_includes_history(self):
        result = self.run_ai("-c", "3", "What happened?")
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = json.loads(result.stdout)
        self.assertIn("line 1\n", prompt)
        self.assertIn("line 12\n", prompt)
        self.assertIn("My Question: What happened?", prompt)
        self.assertNotIn("My Question: 3", prompt)

    def test_quoted_numeric_question_is_not_a_screen_count(self):
        result = self.run_ai("-c", "3 reasons this failed?")
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = json.loads(result.stdout)
        self.assertIn("My Question: 3 reasons this failed?", prompt)
        self.assertNotIn("line 8\n", prompt)

    def test_lines_implies_context_and_limits_total(self):
        result = self.run_ai("-n", "3", "What happened?")
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = json.loads(result.stdout)
        self.assertIn("line 10\nline 11\nline 12\n", prompt)
        self.assertNotIn("line 9\n", prompt)

    def test_context_and_lines_still_work_together(self):
        result = self.run_ai("-c", "-n", "3", "What happened?")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("line 10\nline 11\nline 12\n", json.loads(result.stdout))

    def test_invalid_screen_counts_and_mixed_limits_fail(self):
        for args in (("-c", "0", "Question"), ("-c", "3", "-n", "2", "Question")):
            with self.subTest(args=args):
                result = self.run_ai(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
