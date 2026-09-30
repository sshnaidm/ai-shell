from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_shell.output import OutputConfig

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

CONFIG_PATH = Path.home() / ".ai-shell.toml"

EXAMPLE_CONFIG = """\
# Default module name from [modules.*]
default = "openai"

[output]
format = "auto"  # Styled terminal output; raw Markdown when piped or redirected.
color = "auto"   # auto, always, or never (for terminal format).
prompt_instructions = true

[modules.openai]
type = "openai"
model = "gpt-6-luna"
# Prefer env vars over storing secrets in this file:
api_key_env = "OPENAI_API_KEY"
# api_key = "sk-..."
# base_url = "https://api.openai.com/v1"

[modules.anthropic]
type = "anthropic"
model = "claude-sonnet-5"
api_key_env = "ANTHROPIC_API_KEY"

[modules.gemini_api]
type = "gemini_api"
model = "gemini-3.8-flash"
api_key_env = "GEMINI_API_KEY"

[modules.vertex]
type = "vertex"
project = "my-gcp-project"
location = "us-central1"
model = "gemini-3.8-flash"

[modules.vertex_anthropic]
type = "vertex"
publisher = "anthropic"
project = "my-gcp-project"
location = "global"
model = "claude-sonnet-5"
max_tokens = 4096

[modules.gemini]
type = "gemini"

[modules.claude]
type = "claude"

[modules.opencode]
type = "opencode"
# model = "anthropic/claude-sonnet-5"

[modules.codex]
type = "codex"

[modules.cursor]
type = "cursor"
# command = "/path/to/cursor/agent"  # Use if another `agent` is first on PATH.

[modules.grok]
type = "grok"
# model = "your-grok-model-id"
"""

DEFAULT_ENV_FOR_TYPE = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini_api": "GEMINI_API_KEY",
}


@dataclass
class ModuleConfig:
    name: str
    type: str
    data: dict[str, Any]


@dataclass
class AppConfig:
    path: Path
    default: str
    modules: dict[str, ModuleConfig]
    output: OutputConfig = field(default_factory=OutputConfig)


class ConfigError(Exception):
    pass


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or CONFIG_PATH
    if not config_path.is_file():
        raise ConfigError(
            f"No config at {config_path}. Run `ai --init-config` to create one."
        )
    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)

    default = raw.get("default")
    modules_raw = raw.get("modules") or {}
    if not isinstance(modules_raw, dict) or not modules_raw:
        raise ConfigError(f"{config_path} has no [modules.*] tables.")

    modules: dict[str, ModuleConfig] = {}
    for name, data in modules_raw.items():
        if not isinstance(data, dict):
            raise ConfigError(f"Module [{name}] must be a table.")
        module_type = data.get("type")
        if not module_type or not isinstance(module_type, str):
            raise ConfigError(f"Module [{name}] needs a string `type`.")
        modules[name] = ModuleConfig(name=name, type=module_type, data=data)

    if not default:
        raise ConfigError(f"{config_path} needs a `default` module name.")
    if default not in modules:
        known = ", ".join(sorted(modules))
        raise ConfigError(f"Default module `{default}` is not defined. Known: {known}.")
    try:
        output = OutputConfig.from_dict(raw.get("output", {}))
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    return AppConfig(path=config_path, default=default, modules=modules, output=output)


def write_example_config(path: Path | None = None, *, force: bool = False) -> Path:
    config_path = path or CONFIG_PATH
    if config_path.exists() and not force:
        raise ConfigError(f"{config_path} already exists. Pass --force to overwrite.")
    config_path.write_text(EXAMPLE_CONFIG, encoding="utf-8")
    return config_path


def resolve_secret(module: ModuleConfig, key: str = "api_key") -> str | None:
    explicit = module.data.get(key)
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    env_name = module.data.get(f"{key}_env")
    if isinstance(env_name, str) and env_name:
        value = os.environ.get(env_name)
        if value:
            return value
    fallback_env = DEFAULT_ENV_FOR_TYPE.get(module.type)
    if fallback_env:
        value = os.environ.get(fallback_env)
        if value:
            return value
        if module.type == "gemini_api":
            return os.environ.get("GOOGLE_API_KEY")
    return None
