from __future__ import annotations

from collections.abc import Mapping
from typing import Any

AI_PURPOSE_SECTIONS: dict[str, tuple[str, ...]] = {
    "cover_letter": ("ai_cover_letter",),
    "vacancy_filter": ("ai_vacancy_filter",),
    "captcha": ("ai_captcha",),
}

LEGACY_AI_PURPOSE_SECTIONS: dict[str, tuple[str, ...]] = {
    "cover_letter": (
        "ollama_cover_letter",
        "openai_cover_letter",
    ),
    "vacancy_filter": (
        "ollama_vacancy_filter",
        "openai_vacancy_filter",
    ),
    "captcha": ("ollama_captcha", "openai_captcha"),
}


def get_ai_section(
    config: Mapping[str, Any],
    purpose: str,
) -> tuple[str, dict[str, Any]]:
    sections = AI_PURPOSE_SECTIONS.get(purpose)
    if not sections:
        raise ValueError(
            f"Неизвестная цель AI: {purpose}. "
            f"Допустимые значения: {list(AI_PURPOSE_SECTIONS)}"
        )

    for section_name in sections:
        candidate = config.get(section_name, {})
        if candidate:
            return section_name, candidate

    legacy_sections = LEGACY_AI_PURPOSE_SECTIONS.get(purpose, ())
    for section_name in legacy_sections:
        candidate = config.get(section_name, {})
        if candidate:
            return section_name, candidate

    raise ValueError(
        f"Не задана AI-конфигурация для '{purpose}'. "
        f"Поддерживаются секции: {', '.join(sections)}"
    )


def get_ai_provider(config_section: str, config: Mapping[str, Any]) -> str:
    if "provider" in config:
        return str(config["provider"])

    prefix = config_section.split("_", 1)[0]
    if prefix == "ollama":
        return "ollama"
    if prefix == "openai":
        return "openai"

    raise ValueError(
        f"В секции '{config_section}' нужен ключ 'provider' "
        "(openai или ollama)."
    )
