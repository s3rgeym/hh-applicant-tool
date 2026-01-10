from __future__ import annotations

import platform
from functools import cache
from os import getenv
from pathlib import Path
from threading import Lock
from typing import Any

from . import jsonutil as json


@cache
def get_config_path() -> Path:
    match platform.system():
        case "Windows":
            return Path(getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
        case "Darwin":
            return Path.home() / "Library" / "Application Support"
        case _:
            return Path(getenv("XDG_CONFIG_HOME", Path.home() / ".config"))


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
            with self._config_path.open(
                "w+", encoding="utf-8", errors="replace"
            ) as fp:
                json.dump(
                    self,
                    fp,
                    indent=2,
                    sort_keys=True,
                )

    __getitem__ = dict.get

    def __repr__(self) -> str:
        return str(self._config_path)
