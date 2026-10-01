# AI Shell

Ask AI a question directly from your shell:

```bash
ai how do I find the largest files in this directory
```

AI Shell provides one `ai` command for configurable AI providers. Use an API such as OpenAI, Anthropic, or Gemini, or an installed CLI such as Claude, Codex, OpenCode, Gemini, Grok, or Cursor Agent. Choose a default provider, switch per question, and optionally include piped input or recent tmux output as context. API answers stream to your terminal; CLI output is passed through as it arrives.

You can also send command output or a file along with your question. The `|` character sends the text from the command on the left to `ai`:

```bash
cat error.log | ai explain this error
git diff | ai summarize these changes
tail -n 100 server.log | ai find the likely cause of the failure
```

These examples work in a regular terminal; tmux is optional. When stdout is a terminal, AI Shell renders headings, emphasis, and code with terminal formatting and syntax highlighting. When you pipe or redirect the answer, the default is raw Markdown. Both behaviors are configurable.

## Quick install

Requires Python 3.10+ and either an API account or an installed, authenticated AI CLI.

**Install once, then use `ai` from any directory—even while another project's virtual environment is active.** You do not need to activate an AI Shell environment each time.

Run the installation commands from this repository's directory. Choose one method below.

### With uv

Install with [uv](https://docs.astral.sh/uv/guides/tools/):

```bash
uv tool install .
```

uv keeps AI Shell and its dependencies in their own environment and puts the `ai` command on your shell's command search path (`PATH`). The command automatically uses that environment, including when you have activated another one.

If uv reports that its executable directory is missing from `PATH`, run:

```bash
uv tool update-shell
```

Then open a new shell.

### With pip

For a simple [pip user install](https://pip.pypa.io/en/stable/user_guide/#user-installs), run this outside any active virtual environment. If one is active, run `deactivate` first:

```bash
python3 -m pip install --user .
export PATH="$HOME/.local/bin:$PATH"
```

On Linux, the command is normally installed as `~/.local/bin/ai`. Add the `export PATH` line to `~/.bashrc` (Bash) or `~/.zshrc` (Zsh) so it is available in new terminals. You can then activate your other project environments and continue using `ai`.

If pip reports **`externally-managed-environment`**, use a dedicated environment with pip instead. This also keeps AI Shell's dependencies separate:

```bash
python3 -m venv "$HOME/.local/share/ai-shell/venv"
"$HOME/.local/share/ai-shell/venv/bin/python" -m pip install .
mkdir -p "$HOME/.local/bin"
ln -s "$HOME/.local/share/ai-shell/venv/bin/ai" "$HOME/.local/bin/ai"
export PATH="$HOME/.local/bin:$PATH"
```

This creates a shortcut to `ai` in `~/.local/bin`. **You never need to activate this environment**; `ai` uses its own Python automatically. Keep that environment directory in place. As above, add the `export PATH` line to your shell configuration once.

After either installation method, check which command your shell will run:

```bash
command -v ai
ai --help
```

If another active environment has its own `ai` command, it may take priority. You can always run `~/.local/bin/ai` explicitly when installed there.

### Set up your provider

Create the configuration file once:

```bash
ai --init-config
```

The generated config defaults to OpenAI. To use that default:

```bash
export OPENAI_API_KEY="your-api-key"
ai explain the difference between a process and a thread
```

Edit `~/.ai-shell.toml` to choose another provider or model. Model IDs in the generated config are examples; use a model available to your account.

## Configuration

Runtime settings live in **`~/.ai-shell.toml`**, regardless of your current directory. `ai --init-config` creates an example file and refuses to overwrite an existing one unless you also pass `--force`. See [ai-shell.toml.example](ai-shell.toml.example) for the full example.

A module is a named configuration for a provider. `default` must name an existing module, and every module needs a `type`.

### Choose a default

This minimal config uses the OpenAI API by default and makes Claude CLI available as an alternative:

```toml
default = "openai"

[modules.openai]
type = "openai"
model = "gpt-6-luna"
api_key_env = "OPENAI_API_KEY"

[modules.claude]
type = "claude"
```

```bash
ai what does exit code 137 mean
ai -m claude what does exit code 137 mean
ai --list-modules
```

Module names are yours to choose. For example, `[modules.work]` and `[modules.personal]` can both have `type = "openai"` with different models, endpoints, or credentials. Pass the **module name** to `-m`.

To use another config file explicitly:

```bash
ai --config /path/to/config.toml explain this error
```

There is no automatic config discovery in the current directory. [AGENTS.md](AGENTS.md) contains repository guidance for contributors and coding agents; AI Shell does not load it as runtime configuration or prepend it to questions. A delegated CLI may load its own project instructions.

### Terminal formatting

Add this section to `~/.ai-shell.toml`, outside any `[modules.*]` table:

```toml
[output]
format = "auto"
color = "auto"
prompt_instructions = true
```

The settings also apply if your existing config has no `[output]` section.

| `format` | Behavior |
| --- | --- |
| `auto` (default) | Styled output in a terminal; raw Markdown when stdout is piped or redirected |
| `terminal` | Render Markdown as terminal headings, emphasis, lists, tables, and highlighted code |
| `plain` | Ask the AI for plain text and copyable commands, then pass its answer through |
| `markdown` | Pass the answer through without rendering or adding formatting instructions |

`color` controls the terminal renderer: `auto` detects terminal support and respects `NO_COLOR`; `always` forces ANSI colors and styles; `never` disables them. It does not control a delegated CLI's own diagnostics or raw output.

The renderer uses [Rich Markdown](https://rich.readthedocs.io/en/stable/markdown.html) to display formatting without the Markdown markers. Terminal answers appear as complete paragraphs, headings, tables, and code blocks arrive; an unfinished block is displayed when the provider stops, including on failure. Plain and Markdown modes pass through chunks immediately.

With `prompt_instructions = true`, terminal mode prepends a short request for concise, simple Markdown for the renderer; plain mode asks for no Markdown. The model is asked not to generate ANSI codes; the terminal renderer applies colors locally. Plain text is a model preference, so it may still include Markdown if the model ignores the instruction. Set `prompt_instructions = false` to keep the prompt unchanged while still using your selected output format.

Override the config for one question:

```bash
ai --format terminal explain symbolic links
ai --format plain give me a command to find large files
ai --format terminal --color never explain this error
ai --format markdown explain DNS > answer.md
ai --format plain explain DNS > answer.txt
```

For example, `ai explain DNS > answer.md` uses raw Markdown under `format = "auto"`. If you always want plain text, set `format = "plain"` in the config. These settings work with both API and CLI modules.

### API keys

Use `api_key_env` to read a key from an environment variable. Alternatively, store a key directly in a module:

```toml
[modules.openai]
type = "openai"
model = "gpt-6-luna"
api_key = "your-api-key"
```

Key lookup tries a nonempty `api_key` first, then `api_key_env`, then the provider's standard environment variable:

| Module type | Standard environment variable |
| --- | --- |
| `openai` | `OPENAI_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `gemini_api` | `GEMINI_API_KEY`, then `GOOGLE_API_KEY` |

Prefer environment variables. If you store keys in the file, keep it private with `chmod 600 ~/.ai-shell.toml`.

### API modules

| Type | API | Configuration |
| --- | --- | --- |
| `openai` | OpenAI-compatible streaming Chat Completions | `model`, API key; optional `base_url` |
| `anthropic` | Anthropic streaming Messages | API key; optional `model`, `base_url`, `max_tokens`, `anthropic_version` |
| `gemini_api` | Gemini streaming content generation | API key; optional `model`, `base_url` |
| `vertex` | Gemini or Anthropic Claude on Google Cloud Vertex AI | `project`; optional `publisher`, `location`, `model`; Claude also accepts `max_tokens`; Application Default Credentials |

For an OpenAI-compatible endpoint, set the API root including its version prefix. AI Shell appends `/chat/completions`:

```toml
[modules.custom_api]
type = "openai"
model = "your-model-id"
base_url = "https://your-api-host.example/v1"
api_key_env = "CUSTOM_AI_API_KEY"
```

The `openai` module currently requires a key even if your custom endpoint does not require authentication.

For Vertex AI:

```toml
[modules.vertex]
type = "vertex"
project = "your-gcp-project"
location = "us-central1"
model = "gemini-3.8-flash"
```

To run **Anthropic Claude through Vertex AI**, add a second module:

```toml
[modules.vertex_anthropic]
type = "vertex"
publisher = "anthropic"
project = "your-gcp-project"
location = "global"
model = "claude-sonnet-5"
max_tokens = 4096
```

```bash
ai -m vertex_anthropic explain this error
```

To use it for every question, set `default = "vertex_anthropic"` at the top of your config.

`publisher` selects the Vertex API format: `google` for Gemini, or `anthropic` for Claude. When omitted, model names beginning with `claude-` select Anthropic; other names select Google. The default location is `global` for Anthropic and `us-central1` for Google.

Claude Sonnet 5 uses the `global` endpoint or a multi-region endpoint (`location = "us"` or `"eu"`). Specific regional endpoints such as `us-central1` are for supported older Claude models. Use the exact Google Cloud model ID from the current [Claude on Google Cloud documentation](https://platform.claude.com/docs/en/build-with-claude/claude-on-vertex-ai); some older IDs include a date suffix.

For local use, establish [Application Default Credentials](https://docs.cloud.google.com/docs/authentication/set-up-adc-local-dev-environment):

```bash
gcloud auth application-default login
```

Both Vertex modules use Google credentials; no Anthropic API key is needed for Claude on Vertex. Enable the Vertex AI API and access to your chosen model in Model Garden, and give your identity permission to invoke it. Model availability depends on the project and location. `max_tokens` limits Claude's generated tokens, including any thinking tokens, and defaults to 4096.

Changing the example config or upgrading AI Shell does not overwrite an existing `~/.ai-shell.toml`; update your own model settings there.

### CLI modules

CLI modules use the selected tool's own authentication and settings. Install and configure that tool separately, and make its executable available on `PATH`.

| Type | Default invocation |
| --- | --- |
| `gemini` | `gemini -p PROMPT` |
| `claude` | `claude -p PROMPT` |
| `opencode` | `opencode run PROMPT` |
| `codex` | `codex exec --skip-git-repo-check PROMPT` |
| `cursor` | `agent -p PROMPT --output-format text` |
| `grok` | `grok --output-format plain -p PROMPT` |

Built-in CLI modules accept `command` to override the executable, `model` to select a model, and `extra_args` to pass additional arguments:

```toml
[modules.codex]
type = "codex"
model = "your-codex-model-id"

[modules.claude]
type = "claude"
model = "your-claude-model-id"

[modules.opencode]
type = "opencode"
model = "anthropic/your-model-id"

[modules.cursor]
type = "cursor"
# command = "/path/to/cursor/agent"  # Use if another `agent` is first on PATH.
# model = "your-cursor-model-id"
# extra_args = ["--flag", "value"]
```

The same `model` setting works for Gemini, Cursor, and Grok CLI modules. Omit it to use the agent's own default. To choose a different model for one question, pass `--model`:

```bash
ai -m codex --model your-other-model-id explain this error
```

`--model` also works with API modules. It overrides the selected module's configured model for that call without changing `~/.ai-shell.toml`. Generic `cli` modules use their tool-specific `args` and `extra_args` instead.

Keep model selection out of `extra_args` when using `model` or `--model`; otherwise the underlying agent receives duplicate model flags.

To use the Grok CLI after signing in with `grok login`, add a module and select it with `-m`:

```toml
[modules.grok]
type = "grok"
# model = "your-grok-model-id"
```

```bash
ai -m grok explain this error
```

Set `default = "grok"` at the top of the config if you want it for every question. The Grok module uses the `grok` executable; Cursor uses its own `agent` executable. Grok's headless plain output prints its answer after the single turn completes.

Commands run in your current directory, with the tool's usual behavior and permissions. The Codex module automatically passes `--skip-git-repo-check`, so you can ask questions from any directory without creating a Git repository. Codex's sandbox and approval settings still apply.

The Cursor module expects the `agent` command from Cursor's CLI. Check `command -v agent` and `agent --help` if it fails. If another tool named `agent` is first on `PATH`, set `command` in `[modules.cursor]` to your Cursor executable's full path. AI Shell checks the default `agent --help` before sending it a Cursor prompt, so a name collision produces an error instead of contacting the wrong provider.

For Codex, AI Shell streams the answer on stdout and buffers stderr (the startup banner, progress messages, and token counts). On a successful exit, those diagnostics are discarded. On failure, they are printed to stderr with the exit code, and `ai` returns Codex's exit code. Use `--debug` to see Codex diagnostics live:

```bash
ai -m codex explain this error
ai -m codex --debug explain this error
```

You can redirect the answer while keeping failures visible: `ai -m codex explain this error > answer.txt`. Other CLI modules pass through stdout and stderr live.

If an older installation reports “Not inside a trusted directory,” add the flag to your config as an immediate workaround:

```toml
[modules.codex]
type = "codex"
extra_args = ["--skip-git-repo-check"]
```

To install this repository's updated code, run `uv tool install --force .` from the repository directory, or repeat the pip installation command you used originally with `--upgrade`.

For another tool, use the generic `cli` type:

```toml
[modules.my_tool]
type = "cli"
command = "/path/to/my-ai-tool"
args = ["ask", "--prompt", "{prompt}"]
```

`{prompt}` is replaced with the complete question and any attached context. Without that placeholder, the prompt is appended as the last argument. Arguments are passed directly to the executable without shell expansion.

## Usage

Ask a question, with or without quotes. Use quotes when the question contains shell characters such as `?`, `$`, or `*`:

```bash
ai explain symbolic links
ai 'What does $? mean in Bash?'
```

Pipe text into the question to include it as context:

```bash
cat error.log | ai explain this error
git diff | ai -m claude summarize these changes
ai write a short explanation of DNS > answer.txt
```

The question is still required when piping input. Each invocation sends a new question; AI Shell does not maintain conversation history.

### Ask about output already in your terminal

[tmux](https://man.openbsd.org/tmux) is a terminal tool that keeps sessions running and can split a terminal into several panels, called panes. AI Shell can read text from the pane where you run `ai`, including output that has scrolled off the screen. This feature requires tmux to be installed and your shell to be running inside it.

Use **`-c`** to send the text currently visible in your tmux pane with your question. Put a number after `-c` to send more screenfuls. Use **`-n NUMBER`** to choose an exact line limit instead:

- `ai -c ...` sends the **visible pane**, whatever its height is.
- `ai -c 3 ...` sends up to **three screenfuls**: the visible pane and two pane heights of earlier output.
- `ai -n 3 ...` sends only the **last 3 lines**.
- `ai -n 100 ...` sends up to the **last 100 lines**. Use this when an error appeared farther back.

tmux knows the current pane height; `-c 3` uses three times that height, up to the output still available in tmux history. To see the height yourself, run `tmux display-message -p '#{pane_height}'`. With `-n`, the number limits the total lines attached, including visible text and earlier output. Blank rows below the terminal cursor are ignored. Both counts must be at least 1. You can still combine `-c -n 3` if you like, but `-n 3` is enough. Do not combine `-c 3` with `-n`. Neither option controls the answer length or reads your shell's command history.

If your question starts with a number, quote the whole question so that number is not read as a screen count: `ai -c '3 reasons this failed?'`.

For example, start tmux, run your build, then ask about its output in the same pane:

```bash
tmux
make
ai -c explain why the build failed
ai -c 3 look at the earlier errors and suggest a fix
ai -n 3 explain the last three lines
ai -n 100 look at the earlier errors and suggest a fix
```

If you do not use tmux, send the output with a pipe instead. To send exactly the last 100 lines of a log, put `-n 100` on **`tail`**:

```bash
tail -n 100 error.log | ai explain these errors
```

`-c` and `-n` require tmux and take precedence over piped input, so omit them when using a pipe. Captured or piped text is sent to the selected provider. Without either, AI Shell sends only the question; delegated CLIs may also use their own workspace context.

| Option | Purpose |
| --- | --- |
| `-m`, `--module NAME` | Select a configured module |
| `--model MODEL` | Override the selected module's model for this call |
| `-c`, `--context` | Attach the visible tmux pane; `-c 3` includes three screenfuls |
| `-n`, `--lines N` | Attach up to the last N tmux pane lines; `-c` is optional |
| `--config PATH` | Use a different config file |
| `--init-config` | Create an example config and exit |
| `--force` | Overwrite the config with `--init-config` |
| `--list-modules` | List configured modules and mark the default |
| `--debug` | Print the selected module and full prompt; also show Codex diagnostics live |
| `--format FORMAT` | Choose auto, terminal, plain, or markdown answer output |
| `--color MODE` | Choose auto, always, or never for the terminal renderer |
| `--help` | Show command help |

Answers go to stdout; AI Shell errors and debug output go to stderr. `--debug` still calls the provider and prints any attached context and formatting instructions in its prompt preview.

## Development checks

Run the same Ruff lint and format checks used by GitHub Actions:

```bash
./scripts/lint.sh
```

The script uses uv to install the locked development dependencies from `uv.lock`.
