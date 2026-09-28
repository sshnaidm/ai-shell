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


def get_tmux_context(lines: int) -> str:
    if not os.environ.get("TMUX"):
        raise RuntimeError(
            "Not inside tmux. Run inside a tmux session, or pipe input instead."
        )
    cmd = ["tmux", "capture-pane", "-p", "-S", f"-{lines}"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout


def main(
    prompt: list[str] | None = typer.Argument(
        None, help="Question for the AI"
    ),
    module: str | None = typer.Option(
        None, "-m", "--module", help="Module name from ~/.ai-shell.toml"
    ),
    context: bool = typer.Option(
        False, "-c", "--context", help="Attach recent tmux pane output"
    ),
    lines: int = typer.Option(
        30, "-n", "--lines", help="Number of tmux lines to capture"
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

    question = " ".join(prompt or []).strip()
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
    if context:
        try:
            context_text = get_tmux_context(lines)
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
