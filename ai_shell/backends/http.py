from __future__ import annotations

import json
import sys
from typing import Any, Callable, Iterator

import httpx

from ai_shell.config import ModuleConfig, resolve_secret


class BackendError(Exception):
    pass


def run_http_module(
    module: ModuleConfig, prompt: str, *, write: Callable[[str], None] | None = None
) -> None:
    write = write if write is not None else _write
    if module.type == "openai":
        _run_openai(module, prompt, write=write)
        return
    if module.type == "anthropic":
        _run_anthropic(module, prompt, write=write)
        return
    if module.type == "gemini_api":
        _run_gemini_api(module, prompt, write=write)
        return
    if module.type == "vertex":
        _run_vertex(module, prompt, write=write)
        return
    raise BackendError(f"Unsupported HTTP type `{module.type}`.")


def _require_model(module: ModuleConfig, default: str | None = None) -> str:
    model = module.data.get("model") or default
    if not model:
        raise BackendError(f"Module [{module.name}] needs `model`.")
    return str(model)


def _require_key(module: ModuleConfig) -> str:
    key = resolve_secret(module)
    if not key:
        raise BackendError(
            f"Module [{module.name}] has no API key. Set `api_key`, `api_key_env`, "
            "or the provider's default environment variable."
        )
    return key


def _iter_sse_data(response: httpx.Response) -> Iterator[str]:
    for line in response.iter_lines():
        if not line:
            continue
        if line.startswith("data:"):
            yield line[5:].strip()


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _run_openai(
    module: ModuleConfig, prompt: str, *, write: Callable[[str], None] = _write
) -> None:
    base_url = str(module.data.get("base_url") or "https://api.openai.com/v1").rstrip(
        "/"
    )
    url = f"{base_url}/chat/completions"
    payload = {
        "model": _require_model(module),
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {_require_key(module)}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=120.0) as client:
        with client.stream("POST", url, headers=headers, json=payload) as response:
            _raise_http(response)
            for data in _iter_sse_data(response):
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                if delta:
                    write(delta)
    write("\n")


def _run_anthropic(
    module: ModuleConfig, prompt: str, *, write: Callable[[str], None] = _write
) -> None:
    base_url = str(module.data.get("base_url") or "https://api.anthropic.com").rstrip(
        "/"
    )
    url = f"{base_url}/v1/messages"
    payload = {
        "model": _require_model(module, "claude-sonnet-5"),
        "max_tokens": int(module.data.get("max_tokens") or 4096),
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }
    headers = {
        "x-api-key": _require_key(module),
        "anthropic-version": str(module.data.get("anthropic_version") or "2023-06-01"),
        "Content-Type": "application/json",
    }
    _stream_anthropic(url, payload, headers=headers, write=write)


def _stream_anthropic(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    write: Callable[[str], None] = _write,
) -> None:
    """Stream Anthropic text from its direct API or Vertex AI."""
    with httpx.Client(timeout=120.0) as client:
        with client.stream("POST", url, headers=headers, json=payload) as response:
            _raise_http(response)
            for data in _iter_sse_data(response):
                event = json.loads(data)
                if event.get("type") == "error":
                    error = event.get("error", {})
                    raise BackendError(
                        f"Anthropic stream error: {error.get('message') or error}"
                    )
                if event.get("type") == "content_block_delta":
                    text = event.get("delta", {}).get("text")
                    if text:
                        write(text)
    write("\n")


def _run_gemini_api(
    module: ModuleConfig, prompt: str, *, write: Callable[[str], None] = _write
) -> None:
    model = _require_model(module, "gemini-3.8-flash")
    key = _require_key(module)
    base_url = str(
        module.data.get("base_url")
        or "https://generativelanguage.googleapis.com/v1beta"
    ).rstrip("/")
    url = f"{base_url}/models/{model}:streamGenerateContent"
    params = {"alt": "sse", "key": key}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    _stream_gemini_like(url, payload, params=params, headers=None, write=write)


def _vertex_token() -> str:
    try:
        import google.auth
        import urllib3
        from google.auth.transport.urllib3 import Request as Urllib3Request
    except ImportError as exc:
        raise BackendError(
            "Vertex module needs google-auth. It should be installed with ai-shell."
        ) from exc
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(Urllib3Request(urllib3.PoolManager()))
    if not creds.token:
        raise BackendError("Could not refresh Google Cloud credentials for Vertex AI.")
    return str(creds.token)


def _run_vertex(
    module: ModuleConfig, prompt: str, *, write: Callable[[str], None] = _write
) -> None:
    project = module.data.get("project")
    if not project:
        raise BackendError(f"Module [{module.name}] needs `project`.")
    configured_model = str(module.data.get("model") or "")
    publisher = module.data.get("publisher") or (
        "anthropic" if configured_model.startswith("claude-") else "google"
    )
    if publisher not in {"google", "anthropic"}:
        raise BackendError(
            f"Module [{module.name}] has unsupported Vertex publisher `{publisher}`. "
            "Use `google` or `anthropic`."
        )
    model = _require_model(
        module, "claude-sonnet-5" if publisher == "anthropic" else "gemini-3.8-flash"
    )
    location = module.data.get("location") or (
        "global" if publisher == "anthropic" else "us-central1"
    )
    if location == "global":
        host = "aiplatform.googleapis.com"
    elif location in {"us", "eu"}:
        host = f"aiplatform.{location}.rep.googleapis.com"
    else:
        host = f"{location}-aiplatform.googleapis.com"
    model_url = (
        f"https://{host}/v1/projects/{project}/locations/{location}"
        f"/publishers/{publisher}/models/{model}"
    )
    headers = {
        "Authorization": f"Bearer {_vertex_token()}",
        "Content-Type": "application/json",
    }
    if publisher == "anthropic":
        payload = {
            "anthropic_version": "vertex-2023-10-16",
            "max_tokens": int(module.data.get("max_tokens") or 4096),
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        _stream_anthropic(
            f"{model_url}:streamRawPredict", payload, headers=headers, write=write
        )
        return

    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    _stream_gemini_like(
        f"{model_url}:streamGenerateContent",
        payload,
        params={"alt": "sse"},
        headers=headers,
        write=write,
    )


def _stream_gemini_like(
    url: str,
    payload: dict[str, Any],
    *,
    params: dict[str, str] | None,
    headers: dict[str, str] | None,
    write: Callable[[str], None] = _write,
) -> None:
    with httpx.Client(timeout=120.0) as client:
        with client.stream(
            "POST", url, params=params, headers=headers, json=payload
        ) as response:
            _raise_http(response)
            for data in _iter_sse_data(response):
                chunk = json.loads(data)
                for candidate in chunk.get("candidates", []):
                    parts = candidate.get("content", {}).get("parts", [])
                    for part in parts:
                        text = part.get("text")
                        if text:
                            write(text)
    write("\n")


def _raise_http(response: httpx.Response) -> None:
    if response.is_success:
        return
    body = response.read().decode("utf-8", errors="replace")
    snippet = body[:500]
    raise BackendError(f"HTTP {response.status_code}: {snippet}")
