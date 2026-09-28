from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

from ai_shell.backends import run_module
from ai_shell.backends.http import BackendError
from ai_shell.config import (
    CONFIG_PATH,
    ConfigError,
    load_config,
    write_example_config,
)
from ai_shell.prompt import build_prompt
from ai_shell.output import ColorMode, OutputFormat, TerminalRenderer

console = Console(stderr=True)


def get_tmux_context(lines: int | None = None, *, screens: int = 1) -> str:
    if not os.environ.get("TMUX"):
        raise RuntimeError(
            "Not inside tmux. Run inside a tmux session, or pipe input instead."
        )
    cmd = ["tmux", "capture-pane", "-p"]
    if lines is not None:
        cmd.extend(["-S", f"-{lines}"])
        limit = lines
    elif screens > 1:
        height_result = subprocess.run(
            ["tmux", "display-message", "-p", "#{pane_height}"],
            capture_output=True, text=True, check=True,
        )
        try:
            height = int(height_result.stdout.strip())
        except ValueError as exc:
            raise RuntimeError("Could not determine the tmux pane height.") from exc
        if height < 1:
            raise RuntimeError("Could not determine the tmux pane height.")
        cmd.extend(["-S", f"-{(screens - 1) * height}"])
        limit = screens * height
    else:
        limit = None
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    captured = res.stdout.splitlines()
    # tmux pads the pane below the cursor with empty rows. Discard that
    # padding before choosing the requested number of recent lines.
    while captured and not captured[-1].strip():
        captured.pop()
    return "\n".join(captured[-limit:] if limit is not None else captured)


def main(
    prompt: list[str] | None = typer.Argument(
        None, help="Question for the AI"
    ),
    module: str | None = typer.Option(
        None, "-m", "--module", help="Module name from ~/.ai-shell.toml"
    ),
    context: bool = typer.Option(
        False, "-c", "--context", help="Attach the visible tmux pane; -c 3 attaches 3 screens"
    ),
    lines: int | None = typer.Option(
        None, "-n", "--lines", min=1,
        help="Attach the last N tmux pane lines (implies -c)",
    ),
    debug: bool = typer.Option(
        False, "--debug", help="Print module and prompt preview; show Codex diagnostics live"
    ),
    output_format: OutputFormat | None = typer.Option(
        None, "--format", help="Answer format: auto, terminal, plain, or markdown"
    ),
    color: ColorMode | None = typer.Option(
        None, "--color", help="Terminal colors: auto, always, or never"
    ),
    list_modules: bool = typer.Option(
        False, "--list-modules", help="List configured modules and exit"
    ),
    init_config: bool = typer.Option(
        False, "--init-config", help=f"Write example config to {CONFIG_PATH}"
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite config when used with --init-config"
    ),
    config_path: Path | None = typer.Option(
        None, "--config", help="Config file (default: ~/.ai-shell.toml)"
    ),
) -> None:
    """Ask an AI a question from the shell using a configured module."""
    if init_config:
        try:
            path = write_example_config(config_path or CONFIG_PATH, force=force)
        except ConfigError as exc:
            console.print(f"[bold red]Error:[/bold red] {exc}")
            raise typer.Exit(1)
        console.print(f"Wrote {path}")
        raise typer.Exit(0)

    try:
        app_config = load_config(config_path)
    except ConfigError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(1)

    if list_modules:
        for name, item in app_config.modules.items():
            mark = " (default)" if name == app_config.default else ""
            console.print(f"{name}: type={item.type}{mark}")
        raise typer.Exit(0)

    question_parts = list(prompt or [])
    screens = 1
    # Typer parses -c as a flag; an optional screen count arrives as the
    # first positional argument, before the question.
    if context and question_parts and question_parts[0].isdecimal():
        screens = int(question_parts.pop(0))
        if screens < 1:
            raise typer.BadParameter("The number of screens must be at least 1.")
        if lines is not None:
            raise typer.BadParameter("Use either -c SCREENS or -n LINES, not both.")
    question = " ".join(question_parts).strip()
    if not question:
        raise typer.BadParameter("Question cannot be empty")

    chosen = module or app_config.default
    if chosen not in app_config.modules:
        known = ", ".join(sorted(app_config.modules))
        console.print(
            f"[bold red]Error:[/bold red] Unknown module `{chosen}`. Known: {known}."
        )
        raise typer.Exit(1)
    selected = app_config.modules[chosen]
    output = app_config.output
    if output_format is not None:
        output.format = output_format
    if color is not None:
        output.color = color
    resolved_format = output.resolve_format(sys.stdout)

    context_text: str | None = None
    if context or lines is not None:
        try:
            context_text = get_tmux_context(lines, screens=screens)
        except FileNotFoundError:
            console.print(
                "[bold red]Error:[/bold red] tmux is not installed or not on PATH."
            )
            raise typer.Exit(1)
        except subprocess.CalledProcessError as e:
            console.print(f"[bold red]Error capturing tmux pane:[/bold red] {e}")
            raise typer.Exit(1)
        except RuntimeError as e:
            console.print(f"[bold red]Error:[/bold red] {e}")
            raise typer.Exit(1)
    elif not sys.stdin.isatty():
        context_text = sys.stdin.read()

    if context_text is not None:
        context_text = context_text.strip() or None

    full_prompt = build_prompt(
        question,
        context_text,
        output_format=resolved_format,
        prompt_instructions=output.prompt_instructions,
    )

    if debug:
        captured = len(context_text or "")
        console.print(f"[dim]Module: {selected.name} ({selected.type})[/dim]")
        console.print(f"[dim]Output format: {resolved_format.value}[/dim]")
        console.print(f"[dim]Captured {captured} characters of context...[/dim]")
        console.print(f"[dim]Prompt Preview:\n{full_prompt}[/dim]")

    renderer = (
        TerminalRenderer(color=output.color)
        if resolved_format == OutputFormat.terminal
        else None
    )
    try:
        # Finish pending blocks on failure too, so partial answers remain visible.
        try:
            run_module(
                selected,
                full_prompt,
                debug=debug,
                write=renderer.write if renderer is not None else None,
            )
        finally:
            if renderer is not None:
                renderer.finish()
    except FileNotFoundError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)
    except subprocess.CalledProcessError as e:
        console.print(
            f"[bold red]Error running {selected.type}:[/bold red] exit code {e.returncode}"
        )
        raise typer.Exit(e.returncode or 1)
    except (BackendError, ValueError) as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


def app() -> None:
    typer.run(main)


if __name__ == "__main__":
    app()
