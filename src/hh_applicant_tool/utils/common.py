import sys
from functools import partial
from typing import Any

print_err = partial(print, file=sys.stderr, flush=True)


def get_proxies_dict(proxy_url: str | None) -> dict[str, str]:
    return {"http": proxy_url, "https": proxy_url} if proxy_url else {}


def remove_none(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: remove_none(v) for k, v in data.items() if v is not None}
    if isinstance(data, list):
        return [remove_none(v) for v in data if v is not None]
    return data
