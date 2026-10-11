from __future__ import annotations

import sys
from functools import partial

print_err = partial(print, file=sys.stderr, flush=True)
