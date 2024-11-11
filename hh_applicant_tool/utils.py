from __future__ import annotations
from datetime import datetime
import hashlib
import json
import platform
import sys
from functools import partial
from pathlib import Path
from threading import Lock
from typing import Any
from os import getenv
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
                with self._config_path.open() as f:
                    try:
                        self.update(json.load(f))
                    except ValueError:
                        pass

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.update(*args, **kwargs)
        self._config_path.parent.mkdir(exist_ok=True, parents=True)
        with self._lock:
            with self._config_path.open("w+") as fp:
                json.dump(self, fp, ensure_ascii=True, indent=2, sort_keys=True)

    __getitem__ = dict.get


def truncate_string(s: str, limit: int = 75, ellipsis: str = "…") -> str:
    return s[:limit] + bool(s[limit:]) * ellipsis


def hash_with_salt(data: str, salt: str = "HorsePenis") -> str:
    # Объединяем данные и соль
    salted_data = data + salt
    # Вычисляем хеш SHA-256
    hashed_data = hashlib.sha256(salted_data.encode()).hexdigest()
    return hashed_data


def fix_datetime(dt: str | None) -> str | None:
    if dt is None:
        return None
    return datetime.strptime(dt, INVALID_ISO8601_FORMAT).isoformat()
