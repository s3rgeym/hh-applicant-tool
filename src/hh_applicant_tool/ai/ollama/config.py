from __future__ import annotations

from collections.abc import Mapping

DEFAULT_HOST_BASE_URL = "http://localhost:11434/v1/chat/completions"


def resolve_base_url(config: Mapping[str, object]) -> str:
    base_url = config.get("base_url")
    if isinstance(base_url, str) and base_url:
        return base_url

    mode = str(config.get("mode") or "host").strip().lower()
    if mode == "host":
        host_url = config.get("host_url")
        if isinstance(host_url, str) and host_url:
            return host_url
        return DEFAULT_HOST_BASE_URL

    if mode == "remote":
        remote_url = config.get("remote_url")
        if isinstance(remote_url, str) and remote_url:
            return remote_url
        raise ValueError(
            "Для ollama.mode=remote нужно задать ollama.remote_url"
        )

    raise ValueError(
        "Параметр ollama.mode должен быть host или remote"
    )


def resolve_ollama_base_url(config: Mapping[str, object]) -> str:
    base_url = config.get("base_url")
    if isinstance(base_url, str) and base_url:
        raise ValueError(
            "Для Ollama не используйте ai_*.base_url. "
            "Укажите ollama.mode=host или ollama.mode=remote "
            "и при необходимости ollama.remote_url."
        )

    return resolve_base_url(config)
