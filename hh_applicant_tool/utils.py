from __future__ import annotations

import ctypes
import hashlib
import json
import platform
import random
import re
import sys
import uuid
from datetime import datetime
from functools import cache, partial
from os import getenv
from pathlib import Path
from threading import Lock
from typing import Any

from .constants import DATETIME_FORMAT

print_err = partial(print, file=sys.stderr, flush=True)


@cache
def get_config_path() -> Path:
    match platform.system():
        case "Windows":
            return Path(getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
        case "Darwin":
            return Path.home() / "Library" / "Application Support"
        case _:
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

    def __repr__(self) -> str:
        return str(self._config_path)


def shorten(s: str, limit: int = 75, ellipsis: str = "…") -> str:
    return s[:limit] + bool(s[limit:]) * ellipsis


def make_hash(data: str) -> str:
    # Вычисляем хеш SHA-256
    return hashlib.sha256(data.encode()).hexdigest()


def parse_datetime(dt: str) -> datetime:
    return datetime.strptime(dt, DATETIME_FORMAT)


def fix_datetime(dt: str | None) -> str | None:
    return parse_datetime(dt).isoformat() if dt is not None else None


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


def fix_windows_color_output() -> None:
    kernel32 = ctypes.windll.kernel32  # ty:ignore[unresolved-attribute]
    # 0x0004 = ENABLE_VIRTUAL_TERMINAL_PROCESSING
    # Берем дескриптор стандартного вывода (stdout)
    handle = kernel32.GetStdHandle(-11)
    mode = ctypes.c_uint()
    kernel32.GetConsoleMode(handle, ctypes.byref(mode))
    kernel32.SetConsoleMode(handle, mode.value | 0x0004)


def bool2str(v: bool) -> str:
    return str(v).lower()


def list2str(items: list[Any] | None) -> str:
    return ",".join(f"{v}" for v in items) if items else ""
