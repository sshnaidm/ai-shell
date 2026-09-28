"""Exercise the installed CLI flow from a directory without a Git repository."""

import json
import os
from pathlib import Path
import select
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class CodexDirectoryTests(unittest.TestCase):
    def run_from_non_git_directory(
        self, extra_args, *, debug=False, expected_exit=0, module_type="codex"
    ):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            codex = root / "codex"
            # Emulate the reported Codex failure without a live AI request.
            codex.write_text(
                f"#!{sys.executable}\n"
                "import json, sys\n"
                "args = sys.argv[1:]\n"
                "if '--skip-git-repo-check' not in args:\n"
                "    sys.exit('Not inside a trusted directory')\n"
                "print('Codex progress log', file=sys.stderr)\n"
                "print(json.dumps(args))\n"
                "if '--fail' in args:\n"
                "    print('Authentication failed', file=sys.stderr)\n"
                "    sys.exit(7)\n"
            )
            codex.chmod(0o755)
            config = root / "config.toml"
            config.write_text(
                'default = "codex"\n'
                '[modules.codex]\n'
                f"type = {json.dumps(module_type)}\n"
                'args = ["exec", "--skip-git-repo-check"]\n'
                f"command = {json.dumps(str(codex))}\n"
                'model = "test-model"\n'
                f"extra_args = {json.dumps(extra_args)}\n"
            )
            environment = os.environ.copy()
            source_root = str(Path(__file__).resolve().parents[1])
            environment["PYTHONPATH"] = os.pathsep.join(
                filter(None, (source_root, environment.get("PYTHONPATH")))
            )
            result = subprocess.run(
                [
                    sys.executable, "-m", "ai_shell.cli", "--config", str(config),
                    *(["--debug"] if debug else []),
                    "how", "to", "find", "large", "files?",
                ],
                cwd=root,
                env=environment,
                input="",
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, expected_exit, result.stderr)
            return result

    def test_codex_works_outside_git_by_default(self):
        args = json.loads(self.run_from_non_git_directory(["--ephemeral"]).stdout)
        self.assertEqual(args[0], "exec")
        self.assertIn("--skip-git-repo-check", args)
        self.assertIn("--ephemeral", args)
        self.assertEqual(args[-3:], ["-m", "test-model", "how to find large files?"])

    def test_existing_workaround_does_not_duplicate_flag(self):
        args = json.loads(self.run_from_non_git_directory(["--skip-git-repo-check"]).stdout)
        self.assertEqual(args.count("--skip-git-repo-check"), 1)

    def test_success_hides_codex_diagnostics_but_keeps_answer(self):
        result = self.run_from_non_git_directory([])
        self.assertEqual(result.stderr, "")
        self.assertIn("how to find large files?", result.stdout)

    def test_failure_replays_diagnostics_and_preserves_exit_code(self):
        result = self.run_from_non_git_directory(["--fail"], expected_exit=7)
        self.assertIn("Codex progress log", result.stderr)
        self.assertIn("Authentication failed", result.stderr)
        self.assertIn("exit code 7", result.stderr)
        self.assertIn("how to find large files?", result.stdout)

    def test_debug_shows_codex_diagnostics_on_success(self):
        result = self.run_from_non_git_directory([], debug=True)
        self.assertIn("Codex progress log", result.stderr)
        self.assertIn("Prompt Preview", result.stderr)

    def test_other_cli_diagnostics_remain_visible(self):
        result = self.run_from_non_git_directory([], module_type="cli")
        self.assertIn("Codex progress log", result.stderr)

    def test_answer_streams_before_codex_finishes_despite_large_stderr(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release"
            codex = root / "codex"
            codex.write_text(
                f"#!{sys.executable}\n"
                "import pathlib, sys, time\n"
                "sys.stderr.write('progress ' * 200000)\n"
                "sys.stderr.flush()\n"
                "print('First part', flush=True)\n"
                f"release = pathlib.Path({str(release)!r})\n"
                "deadline = time.monotonic() + 10\n"
                "while not release.exists():\n"
                "    if time.monotonic() > deadline: sys.exit(2)\n"
                "    time.sleep(0.01)\n"
                "print('Last part', flush=True)\n"
            )
            codex.chmod(0o755)
            config = root / "config.toml"
            config.write_text(
                'default = "codex"\n[modules.codex]\ntype = "codex"\n'
                f"command = {json.dumps(str(codex))}\n"
            )
            with subprocess.Popen(
                [sys.executable, "-m", "ai_shell.cli", "--config", str(config), "Question"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ) as process:
                try:
                    readable, _, _ = select.select([process.stdout], [], [], 5)
                    self.assertTrue(readable, "Answer was buffered or stderr blocked the child")
                    self.assertEqual(process.stdout.readline(), "First part\n")
                    self.assertIsNone(process.poll(), "Codex should still be running")
                    release.touch()
                    output, errors = process.communicate(timeout=5)
                    self.assertEqual(output, "Last part\n")
                    self.assertEqual(errors, "")
                    self.assertEqual(process.returncode, 0)
                finally:
                    release.touch()
                    if process.poll() is None:
                        process.kill()
                        process.communicate()


if __name__ == "__main__":
    unittest.main()
