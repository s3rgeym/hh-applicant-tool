import sys
from functools import partial
from typing import Any

print_err = partial(print, file=sys.stderr, flush=True)


def get_proxies_dict(proxy_url: str | None) -> dict[str, str]:
    return {"http": proxy_url, "https": proxy_url} if proxy_url else {}
