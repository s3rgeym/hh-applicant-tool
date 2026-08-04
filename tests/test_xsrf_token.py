"""Тесты выбора XSRF-токена для отклика на вакансии с тестом.

Причина бага: на странице hh.ru бывает несколько `xsrfToken`. Первое
вхождение — случайное значение, оно ротируется при каждой загрузке и не
соответствует cookie `_xsrf`. Из-за этого POST на
`/applicant/vacancy_response/popup` возвращал 403 (CSRF mismatch).

Сервер валидирует именно cookie `_xsrf`, поэтому инструмент должен слать
значение из этой cookie, а не первое вхождение из HTML.
"""

from __future__ import annotations

from http.cookiejar import Cookie, CookieJar

import pytest

from hh_applicant_tool.main import HHApplicantTool


def cookie_jar(data: dict[str, str]) -> CookieJar:
    """Настоящий CookieJar из данных {name: value} (домен .hh.ru)."""
    jar = CookieJar()
    for name, value in data.items():
        jar.set_cookie(
            Cookie(
                version=0,
                name=name,
                value=value,
                port=None,
                port_specified=False,
                domain=".hh.ru",
                domain_specified=True,
                domain_initial_dot=True,
                path="/",
                path_specified=True,
                secure=False,
                expires=None,
                discard=True,
                comment=None,
                comment_url=None,
                rest={},
                rfc2109=False,
            )
        )
    return jar


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeSession:
    def __init__(
        self,
        cookies: dict[str, str] | None = None,
        page_text: str = "",
    ) -> None:
        self.cookies = cookie_jar(cookies or {})
        self._page_text = page_text

    def get(self, _url: str, **_kwargs):
        return FakeResponse(self._page_text)


def make_tool(
    cookies: dict[str, str] | None = None,
    page_text: str = "",
) -> HHApplicantTool:
    # Создаем экземпляр, не запуская __init__ (тот строит argparse и читает диск).
    tool = HHApplicantTool.__new__(HHApplicantTool)
    tool.session = FakeSession(cookies, page_text)
    return tool


def page_html(*tokens: str, escaped: bool = False) -> str:
    """Собирает HTML с несколькими полями `,"xsrfToken":"..."`."""
    q = "&quot;" if escaped else '"'
    return "".join(f',{q}xsrfToken{q}:{q}{t}{q}' for t in tokens)


class TestXsrfTokenFromCookie:
    """xsrf_token должен отдавать значение cookie `_xsrf` — оно и есть токен."""

    def test_returns_cookie_when_present(self):
        tool = make_tool(cookies={"_xsrf": "SESSION_TOKEN"})
        assert tool.xsrf_token == "SESSION_TOKEN"

    def test_does_not_hit_network_when_cookie_present(self):
        session = FakeSession(cookies={"_xsrf": "SESSION_TOKEN"})
        tool = HHApplicantTool.__new__(HHApplicantTool)
        tool.session = session
        _ = tool.xsrf_token
        # cookie есть — страница не должна запрашиваться
        assert session._page_text == ""

    def test_fetches_page_when_cookie_missing(self):
        tool = make_tool(cookies={}, page_text=page_html("EXTRACTED", "OTHER"))
        assert tool.xsrf_token == "EXTRACTED"


class TestExtractPrefersCookie:
    """_extract_xsrf_token должен выбирать вхождение, равное cookie `_xsrf`."""

    def test_prefers_cookie_matching_occurrence(self):
        # Первое вхождение — «декорация», совпадает с cookie только второе
        tool = make_tool(
            cookies={"_xsrf": "REAL_TOKEN"},
            page_text=page_html("ROTATING_DECOY", "REAL_TOKEN"),
        )
        assert tool._extract_xsrf_token(tool.session._page_text) == "REAL_TOKEN"

    def test_falls_back_to_first_when_cookie_not_in_page(self):
        tool = make_tool(
            cookies={"_xsrf": "STALE"},
            page_text=page_html("FIRST", "SECOND"),
        )
        assert tool._extract_xsrf_token(tool.session._page_text) == "FIRST"

    def test_unescapes_html_entities(self):
        tool = make_tool(
            cookies={"_xsrf": "REAL_TOKEN"},
            page_text=page_html("REAL_TOKEN", escaped=True),
        )
        assert tool._extract_xsrf_token(tool.session._page_text) == "REAL_TOKEN"

    def test_raises_when_no_token(self):
        tool = make_tool(cookies={}, page_text="<html>no token here</html>")
        with pytest.raises(ValueError, match="xsrf token not found"):
            tool._extract_xsrf_token(tool.session._page_text)
