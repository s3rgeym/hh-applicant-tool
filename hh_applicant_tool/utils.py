from __future__ import annotations

import json
import sys
from functools import partial
from pathlib import Path
from threading import Lock
from typing import Any

print_err = partial(print, file=sys.stderr, flush=True)


class AttrDict(dict):
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


# TODO: добавить defaults
class Config(dict):
    def __init__(self, config_path: str | Path):
        self._config_path = Path(config_path)
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
                json.dump(
                    self, fp, ensure_ascii=True, indent=2, sort_keys=True
                )

    __getitem__ = dict.get


def truncate_string(s: str, limit: int = 75, ellipsis: str = "…") -> str:
    return s[:limit] + bool(s[limit:]) * ellipsis
