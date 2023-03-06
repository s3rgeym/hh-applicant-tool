from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from threading import Lock
from typing import Any

json_dump_kwargs = dict(indent=2, ensure_ascii=False, sort_keys=True, default=str)
dump = partial(json.dump, **json_dump_kwargs)
dumps = partial(json.dumps, **json_dump_kwargs)


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
            with self._config_path.open("w+") as f:
                dump(self, f)

    __getitem__ = dict.get
