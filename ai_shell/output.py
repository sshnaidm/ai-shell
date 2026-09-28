"""Render answers for terminals while preserving raw output for pipes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
import sys
from typing import Any, TextIO

from rich.console import Console
from rich.markdown import Markdown


class OutputFormat(str, Enum):
    auto = "auto"
    terminal = "terminal"
    plain = "plain"
    markdown = "markdown"


class ColorMode(str, Enum):
    auto = "auto"
    always = "always"
    never = "never"


@dataclass
class OutputConfig:
    format: OutputFormat = OutputFormat.auto
    color: ColorMode = ColorMode.auto
    prompt_instructions: bool = True

    @classmethod
    def from_dict(cls, data: Any) -> OutputConfig:
        if not isinstance(data, dict):
            raise ValueError("[output] must be a table.")
        try:
            format = OutputFormat(data.get("format", "auto"))
            color = ColorMode(data.get("color", "auto"))
        except ValueError as exc:
            raise ValueError(
                "[output] format must be auto, terminal, plain, or markdown; "
                "color must be auto, always, or never."
            ) from exc
        instructions = data.get("prompt_instructions", True)
        if not isinstance(instructions, bool):
            raise ValueError("[output] prompt_instructions must be true or false.")
        return cls(format=format, color=color, prompt_instructions=instructions)

    def resolve_format(self, stream: TextIO) -> OutputFormat:
        if self.format == OutputFormat.auto:
            return OutputFormat.terminal if stream.isatty() else OutputFormat.markdown
        return self.format


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_HEADING = re.compile(r"^ {0,3}#{1,6}\s+")


class TerminalRenderer:
    """Render complete Markdown blocks without clearing or redrawing the screen."""

    def __init__(self, stream: TextIO | None = None, *, color: ColorMode = ColorMode.auto):
        stream = stream if stream is not None else sys.stdout
        self.console = Console(
            file=stream,
            force_terminal=True if color == ColorMode.always else None,
            color_system=None if color == ColorMode.never else "auto",
            no_color=False if color == ColorMode.always else None,
        )
        self.stream = stream
        self.partial = ""
        self.block: list[str] = []
        self.fence: str | None = None

    def write(self, text: str) -> None:
        self.partial += text
        while "\n" in self.partial:
            line, self.partial = self.partial.split("\n", 1)
            self._line(line)

    def _line(self, line: str) -> None:
        fence_match = _FENCE.match(line)
        if self.fence is not None:
            self.block.append(line)
            if (
                fence_match
                and fence_match[1][0] == self.fence[0]
                and len(fence_match[1]) >= len(self.fence)
                and not fence_match[2].strip()
            ):
                self.fence = None
                self._render_block()
        elif fence_match:
            self._render_block()
            self.fence = fence_match[1]
            self.block.append(line)
        elif not line.strip():
            self._render_block()
            self.console.print()
        elif _HEADING.match(line):
            self._render_block()
            self.block.append(line)
            self._render_block()
        else:
            self.block.append(line)

    def _render_block(self) -> None:
        if self.block:
            self.console.print(Markdown("\n".join(self.block)))
            self.block.clear()
            self.stream.flush()

    def finish(self) -> None:
        if self.partial:
            self._line(self.partial)
            self.partial = ""
        self._render_block()
        self.stream.flush()
