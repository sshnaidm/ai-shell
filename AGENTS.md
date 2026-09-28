# AI Shell

This file is for people and coding agents working **on this repository**. It is not loaded when you run `ai` from some other directory.

`ai` is a global shell command. Runtime settings (default module, API keys, CLI binaries) live in `~/.ai-shell.toml`, not here. Example: [ai-shell.toml.example](ai-shell.toml.example). Create yours with `ai --init-config`.

## Usage

```bash
uv pip install -e .
ai --init-config
# edit ~/.ai-shell.toml: set `default` and keys/env vars
ai why did my build fail
ai -m claude summarize this error
ai -c "what failed above"
ai -c 3 "what failed in the last three screens"
ai -n 3 "explain the last three lines"
dmesg | ai explain this
ai --list-modules
```

`-m` selects a named table under `[modules.*]`. Types:

- CLI: `gemini`, `claude`, `opencode`, `codex`, `cursor`, `grok`, or generic `cli`
- HTTP: `openai`, `gemini_api`, `anthropic`, `vertex`

The `vertex` type supports Gemini and Claude. Set `publisher = "anthropic"`
for Claude (also inferred from a `claude-` model name). Claude Sonnet 5 uses
`location = "global"`, `"us"`, or `"eu"`; authentication uses Google ADC.

Prefer `api_key_env` over putting secrets in the TOML file.

`[output]` configures `format` (auto, terminal, plain, markdown), `color`
(auto, always, never), and `prompt_instructions` (boolean). Auto renders rich
terminal output for TTY stdout and passes raw output through for pipes.
`--format` and `--color` override the config for one call. Formatting instructions
are added to terminal/plain prompts when enabled; colors are applied locally.

## Layout

- `ai_shell/cli.py` — Typer entry (`ai`)
- `ai_shell/config.py` — `~/.ai-shell.toml`
- `ai_shell/output.py` — output settings and streaming terminal renderer
- `ai_shell/backends/cli.py` — subprocess modules
- `ai_shell/backends/http.py` — OpenAI / Anthropic / Gemini / Vertex
