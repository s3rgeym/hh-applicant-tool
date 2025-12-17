from __future__ import annotations

import hashlib
import json
import platform
import random
import re
import sys
import uuid
from datetime import datetime
from functools import partial
from os import getenv
from pathlib import Path
from threading import Lock
from typing import Any

from .constants import INVALID_ISO8601_FORMAT

print_err = partial(print, file=sys.stderr, flush=True)


def get_config_path() -> Path:
    match platform.system():
        case "Windows":
            return Path(getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
        case "Darwin":  # macOS
            return Path.home() / "Library" / "Application Support"
        case _:  # Linux and etc
            return Path(getenv("XDG_CONFIG_HOME", Path.home() / ".config"))


class AttrDict(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


# TODO: добавить defaults
class Config(dict):
    def __init__(self, config_path: str | Path | None = None):
        self._config_path = Path(config_path or get_config_path())
        self._lock = Lock()
        self.load()

    def load(self) -> None:
        if self._config_path.exists():
            with self._lock:
                with self._config_path.open(
                    "r", encoding="utf-8", errors="replace"
                ) as f:
                    self.update(json.load(f))

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.update(*args, **kwargs)
        self._config_path.parent.mkdir(exist_ok=True, parents=True)
        with self._lock:
            with self._config_path.open("w+", encoding="utf-8", errors="replace") as fp:
                json.dump(
                    self,
                    fp,
                    ensure_ascii=True,
                    indent=2,
                    sort_keys=True,
                )

    __getitem__ = dict.get


def truncate_string(s: str, limit: int = 75, ellipsis: str = "…") -> str:
    return s[:limit] + bool(s[limit:]) * ellipsis


def make_hash(data: str) -> str:
    # Вычисляем хеш SHA-256
    return hashlib.sha256(data.encode()).hexdigest()


def parse_invalid_datetime(dt: str) -> datetime:
    return datetime.strptime(dt, INVALID_ISO8601_FORMAT)


def fix_datetime(dt: str | None) -> str | None:
    return parse_invalid_datetime(dt).isoformat() if dt is not None else None


def random_text(s: str) -> str:
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


def parse_interval(interval: str) -> tuple[float, float]:
    """Парсит строку интервала и возвращает кортеж с минимальным и максимальным значениями."""
    if "-" in interval:
        min_interval, max_interval = map(float, interval.split("-"))
    else:
        min_interval = max_interval = float(interval)
    return min(min_interval, max_interval), max(min_interval, max_interval)


def android_user_agent() -> str:
    """Android Default"""
    devices = "23053RN02A, 23053RN02Y, 23053RN02I, 23053RN02L, 23077RABDC".split(", ")
    device = random.choice(devices)
    minor = random.randint(100, 150)
    patch = random.randint(10000, 15000)
    android = random.randint(11, 15)
    return (
        f"ru.hh.android/7.{minor}.{patch}, Device: {device}, "
        f"Android OS: {android} (UUID: {uuid.uuid4()})"
    )
