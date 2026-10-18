from __future__ import annotations

import html
import random
import re
from difflib import SequenceMatcher
from typing import Any


def choose_similar(input_text: str, options: list[str]) -> str | None:
    """Возвращает элемент из options, максимально похожий на input_text."""
    if not options:
        return None

    def normalize(s: str) -> str:
        return " ".join(s.casefold().split())

    query = normalize(input_text)

    def score(option: str) -> float:
        return SequenceMatcher(None, query, normalize(option)).ratio()

    return max(options, key=score)


def shorten(s: str, limit: int = 75, ellipsis: str = "…") -> str:
    return s[:limit] + bool(s[limit:]) * ellipsis


def rand_text(s: str) -> str:
    while (
        temp := re.sub(
            r"{([^{}]+)}",
            lambda m: random.choice(
                m.group(1).split("|"),
            ),
            s,
        )
    ) != s:
        s = temp
    return s


def render_template(
    template: str,
    placeholders: dict[str, str],
    name: str = "шаблоне",
    *,
    randomize_text: bool = False,
    escape_html: bool = False,
) -> str:
    """Подставляет плейсхолдеры `%(имя)s`, а неизвестный плейсхолдер
    превращает из невнятного `KeyError: 'имя'` в понятную ошибку."""
    if randomize_text:
        template = rand_text(template)
    if escape_html:
        placeholders = {k: html.escape(v) for k, v in placeholders.items()}
    try:
        return template % placeholders
    except KeyError as ex:
        raise ValueError(
            f"Неизвестный плейсхолдер %({ex.args[0]})s в {name}. "
            f"Доступные: {', '.join(sorted(placeholders))}"
        ) from ex


def bool2str(v: Any) -> str:
    """
    Возвращает переданное значение в виде строки: true/false

        >>> bool2str(1)
        'true'
        >>> bool2str(True)
        'true'
        >>> bool2str({})
        'false'
        >>> bool2str(' ')
        'true'
    """
    return str(bool(v)).lower()


# К удалению
def list2str(items: list[Any] | None) -> str:
    return ",".join(f"{v}" for v in items) if items else ""


# Не нужна
def unescape_string(text: str) -> str:
    if not text:
        return ""
    return (
        text.replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\t", "\t")
        .replace(r"\\", "\\")
    )


def br2nl(s: str) -> str:
    return re.sub(r"<br\s*/?>", "\n", s, flags=re.I)


def strip_tags(content: str) -> str:
    content = br2nl(content)
    content = re.sub(r"<[^>]+>", "", content)
    # content = re.sub(r"\s+", " ", content)
    return content.strip()
