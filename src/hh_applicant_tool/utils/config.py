from __future__ import annotations

import json
import warnings
from abc import ABC, abstractmethod
from functools import cache
from pathlib import Path
from threading import Lock
from typing import Any

import tomli_w
import tomllib

from . import system
from .common import remove_none
from .package import PACKAGE_NAME


@cache
def get_config_directory() -> Path:
    return system.get_config_directory() / PACKAGE_NAME


class Config(dict, ABC):
    """Базовый словарь, который может сохраняться на диск и загружаться с него.

    Путь к файлу задаётся явно. Наследники задают формат файла
    через методы чтения/записи (`_read` / `_write`).
    """

    def __init__(self, config_path: str | Path):
        super().__init__()
        self._config_path = Path(config_path)
        self._lock = Lock()
        self.load()

    @abstractmethod
    def _read(self) -> dict[str, Any]:
        """Прочитать данные с диска. Вызывается под блокировкой."""

    @abstractmethod
    def _write(self, data: dict[str, Any]) -> None:
        """Записать данные на диск. Вызывается под блокировкой."""

    def _after_save(self) -> None:
        """Хук, вызываемый после успешного сохранения."""

    def load(self) -> None:
        with self._lock:
            self.update(self._read())

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.update(*args, **kwargs)
        self._config_path.parent.mkdir(exist_ok=True, parents=True)
        with self._lock:
            self._write(dict(self))
        self._after_save()

    __getitem__ = dict.get

    def __str__(self) -> str:
        return str(self._config_path)


class ConfigJSON(Config):
    """Конфиг в формате JSON."""

    def _read(self) -> dict[str, Any]:
        if not self._config_path.exists():
            return {}
        with self._config_path.open(
            "r", encoding="utf-8", errors="replace"
        ) as f:
            return json.load(f)

    def _write(self, data: dict[str, Any]) -> None:
        with self._config_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=True, separators=(",", ":"))


class ConfigTOML(Config):
    """Конфиг в формате TOML (с запасным чтением старого JSON)."""

    @property
    def _legacy_path(self) -> Path:
        # Запасной формат (только чтение): JSON рядом с основным файлом.
        return self._config_path.with_suffix(".json")

    def _read(self) -> dict[str, Any]:
        if self._config_path.exists():
            with self._config_path.open("rb") as f:
                return tomllib.load(f)
        if self._legacy_path.exists():
            with self._legacy_path.open(
                "r", encoding="utf-8", errors="replace"
            ) as f:
                return json.load(f)
        return {}

    def _write(self, data: dict[str, Any]) -> None:
        with self._config_path.open("wb") as f:
            # TOML не поддерживает None
            tomli_w.dump(remove_none(data), f, multiline_strings=True, indent=2)

    def _after_save(self) -> None:
        if (
            self._legacy_path.exists()
            and self._config_path != self._legacy_path
        ):
            warnings.warn(
                f"Конфиг старого формата JSON больше не используется. Файл {self._legacy_path!s} можно удалить.",
                UserWarning,
                stacklevel=3,
            )
