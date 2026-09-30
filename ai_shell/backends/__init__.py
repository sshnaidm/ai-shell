from __future__ import annotations

from typing import Callable

from ai_shell.backends.cli import run_cli_module
from ai_shell.backends.http import run_http_module
from ai_shell.config import ModuleConfig

CLI_TYPES = frozenset({"gemini", "claude", "opencode", "codex", "cursor", "grok", "cli"})
HTTP_TYPES = frozenset({"openai", "gemini_api", "anthropic", "vertex"})


def run_module(
    module: ModuleConfig,
    prompt: str,
    *,
    debug: bool = False,
    write: Callable[[str], None] | None = None,
) -> None:
    if module.type in CLI_TYPES:
        run_cli_module(module, prompt, debug=debug, write=write)
        return
    if module.type in HTTP_TYPES:
        run_http_module(module, prompt, write=write)
        return
    known = ", ".join(sorted(CLI_TYPES | HTTP_TYPES))
    raise ValueError(f"Unknown module type `{module.type}`. Known types: {known}.")
