from typing import Any

_SENTINEL = object()


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
