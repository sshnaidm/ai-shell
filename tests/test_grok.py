"""Grok CLI routing with a local stand-in; no API call is made."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_shell.config import EXAMPLE_CONFIG


class GrokCliTests(unittest.TestCase):
    def test_default_grok_binary_gets_one_question_and_plain_output(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            grok = root / "grok"
            grok.write_text(
                f"#!{sys.executable}\n"
                "import json, sys\n"
                "print(json.dumps(sys.argv[1:]))\n"
            )
            grok.chmod(0o755)
            config = root / "config.toml"
            config.write_text(
                'default = "grok"\n'
                "[modules.grok]\n"
                'type = "grok"\n'
                'model = "test-model"\n'
                'extra_args = ["--max-turns", "1"]\n'
            )
            environment = os.environ.copy()
            environment["PATH"] = f"{root}{os.pathsep}{environment.get('PATH', '')}"
            source_root = str(Path(__file__).resolve().parents[1])
            environment["PYTHONPATH"] = os.pathsep.join(
                filter(None, (source_root, environment.get("PYTHONPATH")))
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ai_shell.cli",
                    "--config",
                    str(config),
                    "What",
                    "is",
                    "this?",
                ],
                cwd=root,
                env=environment,
                input="",
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout),
                [
                    "--max-turns",
                    "1",
                    "--output-format",
                    "plain",
                    "-m",
                    "test-model",
                    "-p",
                    "What is this?",
                ],
            )

    def test_generated_config_offers_grok_module(self):
        with TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            config.write_text(EXAMPLE_CONFIG)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "ai_shell.cli",
                    "--config",
                    str(config),
                    "--list-modules",
                ],
                input="",
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("grok: type=grok", result.stderr)


if __name__ == "__main__":
    unittest.main()
