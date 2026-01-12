from __future__ import annotations

from datetime import datetime
from typing import Any

DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def parse_api_datetime(dt: str) -> datetime:
    return datetime.strptime(dt, DATETIME_FORMAT)


def try_parse_datetime(dt: Any) -> datetime | Any:
    for parse in (datetime.fromisoformat, parse_api_datetime):
        try:
            return parse(dt)
        except (ValueError, TypeError):
            pass
    return dt
