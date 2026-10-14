from __future__ import annotations

import sys
from functools import partial
from typing import Any

_SENTINEL = object()
print_err = partial(print, file=sys.stderr, flush=True)


def get_proxies_dict(proxy_url: str | None) -> dict[str, str]:
    return {"http": proxy_url, "https": proxy_url} if proxy_url else {}


def remove_none(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: remove_none(v) for k, v in data.items() if v is not None}
    if isinstance(data, list):
        return [remove_none(v) for v in data if v is not None]
    return data


def find_key(data: Any, target_key: str, default: Any = None) -> Any:
    if isinstance(data, dict):
        if target_key in data:
            return data[target_key]

        for value in data.values():
            result = find_key(value, target_key, _SENTINEL)
            if result is not _SENTINEL:
                return result

    elif isinstance(data, list):
        for item in data:
            result = find_key(item, target_key, _SENTINEL)
            if result is not _SENTINEL:
                return result

    return default
