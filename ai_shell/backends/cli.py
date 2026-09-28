from __future__ import annotations

import codecs
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable, TextIO

from ai_shell.config import ModuleConfig

DEFAULT_COMMANDS = {
    "gemini": "gemini",
    "claude": "claude",
    "opencode": "opencode",
    "codex": "codex",
    "cursor": "agent",
    "grok": "grok",
}


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list):
        return [str(item) for item in value]
    raise ValueError("extra_args / args must be a string or list of strings")


def _substitute_prompt(parts: list[str], prompt: str) -> list[str]:
    if any("{prompt}" in part for part in parts):
        return [part.replace("{prompt}", prompt) for part in parts]
    return [*parts, prompt]


def build_argv(module: ModuleConfig, prompt: str) -> list[str]:
    command = str(module.data.get("command") or DEFAULT_COMMANDS.get(module.type) or "")
    if not command:
        raise ValueError(f"Module [{module.name}] needs `command`.")

    extra = _as_str_list(module.data.get("extra_args"))
    model = module.data.get("model")

    if module.type == "cli":
        args = _as_str_list(module.data.get("args"))
        return [command, *_substitute_prompt([*args, *extra], prompt)]

    if module.type == "gemini":
        argv = [command, *extra, "-p", prompt]
        if model:
            argv[1:1] = ["-m", str(model)]
        return argv

    if module.type == "claude":
        argv = [command, *extra, "-p", prompt]
        if model:
            argv.extend(["--model", str(model)])
        return argv

    if module.type == "opencode":
        argv = [command, "run", *extra]
        if model:
            argv.extend(["-m", str(model)])
        argv.append(prompt)
        return argv

    if module.type == "codex":
        # `ai` is a global Q&A command, including outside Git repositories.
        argv = [command, "exec"]
        if "--skip-git-repo-check" not in extra:
            argv.append("--skip-git-repo-check")
        argv.extend(extra)
        if model:
            argv.extend(["-m", str(model)])
        argv.append(prompt)
        return argv

    if module.type == "cursor":
        argv = [command, *extra, "-p", prompt, "--output-format", "text"]
        if model:
            argv.extend(["--model", str(model)])
        return argv

    if module.type == "grok":
        argv = [command, *extra, "--output-format", "plain"]
        if model:
            argv.extend(["-m", str(model)])
        argv.extend(["-p", prompt])
        return argv

    raise ValueError(f"Unsupported CLI type `{module.type}`.")


def _run_command(
    argv: list[str],
    *,
    stderr: TextIO | None = None,
    write: Callable[[str], None] | None = None,
) -> None:
    if write is None:
        subprocess.run(argv, stderr=stderr, check=True)
        return

    # Read chunks rather than lines so API-like CLI output is also streamed.
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=stderr) as process:
        assert process.stdout is not None
        while chunk := os.read(process.stdout.fileno(), 4096):
            write(decoder.decode(chunk))
        write(decoder.decode(b"", final=True))
        returncode = process.wait()
        if returncode:
            raise subprocess.CalledProcessError(returncode, argv)


def run_cli_module(
    module: ModuleConfig,
    prompt: str,
    *,
    debug: bool = False,
    write: Callable[[str], None] | None = None,
) -> None:
    argv = build_argv(module, prompt)
    try:
        if module.type == "cursor" and not module.data.get("command"):
            # Other tools also install an `agent` executable. Do not send a
            # Cursor prompt to whichever unrelated tool appears first on PATH.
            detected = subprocess.run(
                [argv[0], "--help"], capture_output=True, text=True,
                timeout=5, check=False,
            )
            if detected.returncode or "cursor agent" not in (
                detected.stdout + detected.stderr
            ).lower():
                found = shutil.which(argv[0]) or argv[0]
                raise ValueError(
                    f"`{argv[0]}` resolves to {found}, which does not appear to be "
                    "Cursor Agent. Install Cursor CLI or set `command` for the "
                    f"`{module.name}` module to the Cursor Agent executable."
                )
        if module.type == "codex" and not debug:
            # Keep stdout live. A file avoids pipe deadlocks and unbounded RAM
            # use when Codex emits a long progress log on stderr.
            with tempfile.TemporaryFile(
                mode="w+", encoding="utf-8", errors="replace"
            ) as diagnostics:
                try:
                    _run_command(argv, stderr=diagnostics, write=write)
                except (subprocess.CalledProcessError, KeyboardInterrupt):
                    diagnostics.seek(0)
                    shutil.copyfileobj(diagnostics, sys.stderr)
                    sys.stderr.flush()
                    raise
        else:
            _run_command(argv, write=write)
    except FileNotFoundError as exc:
        binary = argv[0]
        raise FileNotFoundError(
            f"Command `{binary}` not found. Install it or set `command` in "
            f"[{module.name}] in ~/.ai-shell.toml."
        ) from exc
