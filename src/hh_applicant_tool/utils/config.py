from __future__ import annotations

import platform
import warnings
from functools import cache
from os import getenv
from pathlib import Path
from threading import Lock
from typing import Any

import tomli_w
import tomllib

from . import json
from .package import PACKAGE_NAME


@cache
def get_config_path() -> Path:
    match platform.system():
        case "Windows":
            return (
                Path(getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
                / PACKAGE_NAME
            )
        case "Darwin":
            return (
                Path.home() / "Library" / "Application Support" / PACKAGE_NAME
            )
        case _:
            return (
                Path(getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
                / PACKAGE_NAME
            )


class Config(dict):
    def __init__(self, config_path: str | Path | None = None):
        self._config_path = Path(
            config_path or get_config_path() / "config.toml"
        )
        # Запасной формат (только чтение): JSON рядом с основным файлом.
        self._legacy_path = self._config_path.with_suffix(".json")
        self._lock = Lock()
        self.load()

    def load(self) -> None:
        with self._lock:
            if self._config_path.exists():
                with self._config_path.open("rb") as f:
                    self.update(tomllib.load(f))
            elif self._legacy_path.exists():
                with self._legacy_path.open(
                    "r", encoding="utf-8", errors="replace"
                ) as f:
                    self.update(json.load(f))

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.update(*args, **kwargs)
        self._config_path.parent.mkdir(exist_ok=True, parents=True)
        with self._lock:
            with self._config_path.open("wb") as fp:
                tomli_w.dump(dict(self), fp, indent=2)
        if (
            self._legacy_path.exists()
            and self._config_path != self._legacy_path
        ):
            warnings.warn(
                f"Конфиг старого формата JSON больше не используется. Файл {self._legacy_path!s} можно удалить."
            )

    __getitem__ = dict.get

    def __repr__(self) -> str:
        return str(self._config_path)
