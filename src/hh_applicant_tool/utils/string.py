from __future__ import annotations

import random
import re
from typing import Any


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


def bool2str(v: bool) -> str:
    return str(v).lower()


def list2str(items: list[Any] | None) -> str:
    return ",".join(f"{v}" for v in items) if items else ""


def unescape_string(text: str) -> str:
    if not text:
        return ""
    return (
        text.replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\t", "\t")
        .replace(r"\\", "\\")
    )
