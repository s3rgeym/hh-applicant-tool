from __future__ import annotations

from .base import AIError

__all__ = [
    "AIError",
    "ChatOpenAI",
    "OpenAIError",
    "ChatOllama",
    "OllamaError",
    "DEFAULT_HOST_BASE_URL",
    "OllamaModelSpec",
    "get_model_spec",
    "resolve_base_url",
    "resolve_ollama_base_url",
    "supported_models",
]


def __getattr__(name: str):
    if name in {"ChatOpenAI", "OpenAIError"}:
        from .openai import ChatOpenAI, OpenAIError

        return {"ChatOpenAI": ChatOpenAI, "OpenAIError": OpenAIError}[name]

    if name in {
        "ChatOllama",
        "OllamaError",
        "DEFAULT_HOST_BASE_URL",
        "OllamaModelSpec",
        "get_model_spec",
        "resolve_base_url",
        "resolve_ollama_base_url",
        "supported_models",
    }:
        from .ollama import (
            ChatOllama,
            DEFAULT_HOST_BASE_URL,
            OllamaError,
            OllamaModelSpec,
            get_model_spec,
            resolve_base_url,
            resolve_ollama_base_url,
            supported_models,
        )

        return {
            "ChatOllama": ChatOllama,
            "OllamaError": OllamaError,
            "DEFAULT_HOST_BASE_URL": DEFAULT_HOST_BASE_URL,
            "OllamaModelSpec": OllamaModelSpec,
            "get_model_spec": get_model_spec,
            "resolve_base_url": resolve_base_url,
            "resolve_ollama_base_url": resolve_ollama_base_url,
            "supported_models": supported_models,
        }[name]

    raise AttributeError(name)
