"""Tests for the universal, terse error summary shown for test-vacancy applies.

The formatter must always return a short, human-readable string and never dump
raw response bodies into the CLI (the real signal is the HTTP status + a single
short recognised detail, not an exhaustive parse of hh.ru's changing API).
"""

from __future__ import annotations

import pytest

from hh_applicant_tool.operations.apply_vacancies import (
    _first_error_detail,
    _format_error_summary,
)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        # Real observed case: 403 + a site page bootstrap (no error keys).
        (
            {
                "_http_status": 403,
                "css_links": ["x.css"],
                "inline_script": "js",
                "sentry_traceparent": "trace",
            },
            "HTTP 403: вместо ответа вернулась страница сайта hh.ru",
        ),
        # Error reported as an errors array (message first).
        (
            {"_http_status": 400, "errors": [{"message": "bad request"}]},
            "HTTP 400: bad request",
        ),
        # errors elements without message -> code/type fallback.
        (
            {"_http_status": 429, "errors": [{"code": "rate_limited"}]},
            "HTTP 429: rate_limited",
        ),
        # Scalar message/error fields.
        ({"_http_status": 500, "message": "boom"}, "HTTP 500: boom"),
        ({"_http_status": 403, "error": "forbidden"}, "HTTP 403: forbidden"),
        # Unknown body -> terse fallback, never a raw dump.
        ({"_http_status": 403, "foo": "bar"}, "HTTP 403: нет данных об ошибке"),
        # Non-dict result must not crash.
        ("not a dict", "нет данных об ошибке"),
        (None, "нет данных об ошибке"),
    ],
)
def test_format_error_summary(result: object, expected: str) -> None:
    assert _format_error_summary(result) == expected


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"errors": [{"message": "m"}]}, "m"),
        ({"errors": [{"code": "c"}]}, "c"),
        ({"error": "single"}, "single"),
        ({"message": "msg"}, "msg"),
        ({"reason": "why"}, "why"),
        ({"foo": 1}, None),
        ("not a dict", None),
    ],
)
def test_first_error_detail(result: object, expected: str | None) -> None:
    assert _first_error_detail(result) == expected
