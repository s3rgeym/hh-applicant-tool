from __future__ import annotations

import hashlib
import sys
from functools import partial


def calc_hash(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


print_err = partial(print, file=sys.stderr, flush=True)
