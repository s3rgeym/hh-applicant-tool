from __future__ import annotations

import json
import tomllib
import warnings
from abc import ABC, abstractmethod
from copy import deepcopy
from functools import cache
from pathlib import Path
from threading import Lock
from typing import Any

import tomli_w

from . import system
from .package import PACKAGE_NAME


@cache
def get_config_directory() -> Path:
    return system.get_config_directory() / PACKAGE_NAME


def remove_none(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: remove_none(v) for k, v in data.items() if v is not None}
    if isinstance(data, list):
        return [remove_none(v) for v in data if v is not None]
    return data


_MISSING = object()


class Config(dict, ABC):
    """Базовый словарь, который может сохраняться на диск и загружаться с него.

    Путь к файлу задаётся явно. Наследники задают формат файла
    через методы чтения/записи (`_read` / `_write`).
    """

    def __init__(self, config_path: str | Path):
        super().__init__()
        self._path = Path(config_path)
        self._lock = Lock()
        self.load()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def file_name(self) -> Path:
        return str(self._path)

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
        self._path.parent.mkdir(exist_ok=True, parents=True)
        with self._lock:
            self._write(dict(self))
        self._after_save()

    def exists(self) -> bool:
        return self._path.exists()

    def unlink(self) -> None:
        self._path.unlink(missing_ok=True)

    def get_value(self, path: str, default: Any = None) -> Any:
        """Значение по пути вида "openai.captcha.model"."""
        data: Any = self
        for key in path.split("."):
            if not isinstance(data, dict) or key not in data:
                return default
            data = data[key]
        return data

    def set_value(self, path: str, value: Any, *, create: bool = False) -> bool:
        """Устанавливает значение по пути.

        По умолчанию меняет только уже существующий ключ и возвращает
        False, если пути нет. С create=True создаёт недостающие секции.
        """
        *keys, last = path.split(".")
        data: Any = self
        for key in keys:
            if not isinstance(data, dict):
                return False
            if key not in data:
                if not create:
                    return False
                data[key] = {}
            data = data[key]
        if not isinstance(data, dict) or (last not in data and not create):
            return False
        data[last] = value
        return True

    def delete_value(self, path: str, *, prune: bool = False) -> bool:
        """Удаляет ключ по пути вида "openai.captcha.model".

        Возвращает False, если пути нет. С prune=True секции, которые
        после удаления остались пустыми, тоже удаляются (вверх по цепочке).
        Изменение только в памяти: чтобы записать на диск, вызови save().
        """
        *keys, last = path.split(".")
        with self._lock:
            chain: list[dict[str, Any]] = [self]
            data: Any = self
            for key in keys:
                if not isinstance(data, dict) or key not in data:
                    return False
                data = data[key]
                chain.append(data)

            if not isinstance(data, dict) or last not in data:
                return False

            del data[last]

            if prune:
                # chain[i] — словарь, в котором лежит keys[i]
                for container, key in zip(
                    reversed(chain[:-1]), reversed(keys), strict=True
                ):
                    if container[key]:
                        break
                    del container[key]
            return True

    def get_section(self, path: str) -> dict[str, Any]:
        """Глубокая копия секции; пустой словарь, если её нет."""
        value = self.get_value(path, _MISSING) # нейробред
        return deepcopy(value) if isinstance(value, dict) else {}

    def get_merged(self, *paths: str) -> dict[str, Any]:
        """Сливает секции по порядку: поздние перекрывают ранние.

        Слияние поверхностное (по ключам верхнего уровня), результат
        независим от конфига. Отсутствующие секции пропускаются.

        >>> config.get_merged("openai.default", "openai.captcha")
        """
        result: dict[str, Any] = {}
        for path in paths:
            result.update(self.get_section(path))
        return result

    # def __str__(self) -> str:
    #     return str(self._path)


class ConfigJSON(Config):
    """Конфиг в формате JSON."""

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        with self._path.open("r", encoding="utf-8", errors="replace") as f:
            return json.load(f)

    def _write(self, data: dict[str, Any]) -> None:
        with self._path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=True, separators=(",", ":"))


class ConfigTOML(Config):
    """Конфиг в формате TOML (с запасным чтением старого JSON)."""

    @property
    def _legacy_path(self) -> Path:
        # Запасной формат (только чтение): JSON рядом с основным файлом.
        return self._path.with_suffix(".json")

    def _read(self) -> dict[str, Any]:
        if self._path.exists():
            with self._path.open("rb") as f:
                return tomllib.load(f)
        if self._legacy_path.exists():
            with self._legacy_path.open(
                "r", encoding="utf-8", errors="replace"
            ) as f:
                return json.load(f)
        return {}

    def _write(self, data: dict[str, Any]) -> None:
        with self._path.open("wb") as f:
            # TOML не поддерживает None
            tomli_w.dump(remove_none(data), f, multiline_strings=True, indent=2)

    def _after_save(self) -> None:
        if self._legacy_path.exists() and self._path != self._legacy_path:
            warnings.warn(
                f"Конфиг старого формата JSON больше не используется. Файл {self._legacy_path!s} можно удалить.",
                UserWarning,
                stacklevel=3,
            )
