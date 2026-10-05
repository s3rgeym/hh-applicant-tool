"""Тесты разбора ответа hh.ru на отправленный ответ капчи.

Причина бага: раньше успех определялся по DOM страницы — ждали, пока
пропадёт поле ввода, а по таймауту объявляли капчу решённой. Зависание
hh.ru при этом считалось успехом, и инструмент уходил откликаться с
капчей, которую никто не проходил.

Теперь успех определяется по самому ответу hh.ru на POST. Правила
разбора сняты с чужого реверса и подтверждены в JS самого hh.ru:

* JSON с `hhcaptcha.isBot` или `recaptcha.isBot` true — отказ;
* 302/303 на `/account/captcha` или `/account/login` — отказ;
* любой другой 302/303, включая совсем пустой `Location`, — принято:
  фронтенд hh.ru трактует 302 у XHR как завершение и сам уходит на
  backurl;
* 200 без маркера `isBot` — принято;
* всё остальное — «непонятно», успехом считать нельзя.

Тесты оффлайн: поддельная сессия отдаёт заготовленные ответы, сеть не
нужна.
"""

from __future__ import annotations

import json

import pytest
import requests

from hh_applicant_tool.api.captcha import (
    CAPTCHA_LANGUAGE_DEFAULT,
    REASON_ACCEPTED,
    CaptchaError,
    CaptchaFlow,
)

STATE = "OYGN7b1YHBH2iTkS4_FNAdKN23WxGkMv_lmQZzOUpmFzTa2xItNRJYygiI3u6"
CAPTCHA_URL = f"https://hh.ru/account/captcha?state={STATE}&lang=en"


class FakeResponse:
    """Ответ hh.ru, собранный из заготовки."""

    def __init__(
        self,
        status_code: int = 200,
        *,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
        url: str = CAPTCHA_URL,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.content = body
        self.url = url

    def json(self) -> object:
        return json.loads(self.content.decode("utf-8"))


class FakeSession:
    """Сессия, которая на записанные вызовы отдаёт заготовленные ответы.

    Порядок вызовов не проверяем: тесты интересует только разбор ответа
    на отправку. Порядок проверяет `test_submit_order`.
    """

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def _next(self, method: str, url: str, kwargs) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        if not self._responses:
            raise AssertionError(f"Лишний запрос {method} {url}")
        return self._responses.pop(0)

    def get(self, url, **kwargs) -> FakeResponse:
        return self._next("GET", url, kwargs)

    def post(self, url, **kwargs) -> FakeResponse:
        return self._next("POST", url, kwargs)


def cookie_jar() -> requests.cookies.RequestsCookieJar:
    """Сессия с кукой `_xsrf`, которую требует флоу."""
    jar = requests.cookies.RequestsCookieJar()
    jar.set("_xsrf", "87ca0842token")
    return jar


def flow(responses: list[FakeResponse], **kwargs) -> CaptchaFlow:
    session = FakeSession(responses)
    session.cookies = cookie_jar()
    return CaptchaFlow(session, CAPTCHA_URL, **kwargs)


def submit_with(response: FakeResponse, **kwargs) -> CaptchaFlow:
    """Прогоняет одну отправку ответа и возвращает флоу для осмотра."""
    instance = flow([response], **kwargs)
    instance.submit("some words", key="key-1")
    return instance


def redirect(location: str = "") -> FakeResponse:
    """302/303 на заданный адрес. Пустой адрес — заголовка нет вовсе."""
    headers = {"Location": location} if location else {}
    return FakeResponse(303, headers=headers)


class TestAccepted:
    """Сигналы, по которым капча пройдена."""

    def test_302_with_empty_location_accepted(self) -> None:
        """Самый частый успех: 302 вообще без заголовка Location.

        Фронтенд hh.ru после такого ответа считает капчу пройденной и
        уходит на backurl сам, поэтому пустой Location — это принято,
        а не «непонятно».
        """
        instance = flow([FakeResponse(302)])
        assert instance.submit("word", key="k").accepted

    def test_303_to_vacancy_accepted(self) -> None:
        instance = flow([redirect("https://hh.ru/vacancy/123456")])
        result = instance.submit("word", key="k")
        assert result.accepted
        assert result.reason == REASON_ACCEPTED

    def test_303_relative_location_accepted(self) -> None:
        instance = flow([redirect("/search/vacancy?text=python")])
        assert instance.submit("word", key="k").accepted

    def test_200_without_isbot_accepted(self) -> None:
        instance = flow([FakeResponse(200, body=b'{"ok": true}')])
        assert instance.submit("word", key="k").accepted

    def test_200_with_empty_body_accepted(self) -> None:
        instance = flow([FakeResponse(200)])
        assert instance.submit("word", key="k").accepted


class TestRejected:
    """Сигналы, по которым hh.ru ответ не принял."""

    def test_isbot_hhcaptcha_rejected(self) -> None:
        instance = flow(
            [FakeResponse(200, body=b'{"hhcaptcha": {"isBot": true}}')]
        )
        result = instance.submit("word", key="k")
        assert not result.accepted
        assert result.reason == "isBot"

    def test_isbot_recaptcha_rejected(self) -> None:
        instance = flow(
            [FakeResponse(200, body=b'{"recaptcha": {"isBot": true}}')]
        )
        assert instance.submit("word", key="k").reason == "isBot"

    def test_isbot_false_is_not_rejection(self) -> None:
        """`isBot: false` — это не отказ, обычный успешный ответ."""
        instance = flow(
            [FakeResponse(200, body=b'{"hhcaptcha": {"isBot": false}}')]
        )
        assert instance.submit("word", key="k").accepted

    def test_redirect_back_to_captcha_rejected(self) -> None:
        instance = flow(
            [redirect("https://hh.ru/account/captcha?state=" + STATE)]
        )
        result = instance.submit("word", key="k")
        assert not result.accepted
        assert result.reason == "redirect_account/captcha"

    def test_redirect_to_login_rejected(self) -> None:
        instance = flow([redirect("https://hh.ru/account/login")])
        result = instance.submit("word", key="k")
        assert not result.accepted
        assert result.reason == "redirect_account/login"

    def test_redirect_relative_to_captcha_rejected(self) -> None:
        instance = flow([redirect("/account/captcha")])
        assert not instance.submit("word", key="k").accepted

    def test_isbot_wins_over_302(self) -> None:
        """Признак бота важнее кода ответа: помечаем отказом."""
        instance = flow(
            [
                FakeResponse(
                    303,
                    headers={"Location": "https://hh.ru/vacancy/1"},
                    body=b'{"hhcaptcha": {"isBot": true}}',
                )
            ]
        )
        assert instance.submit("word", key="k").reason == "isBot"


class TestUnknown:
    """Сигналы, которые нельзя уверенно назвать успехом или отказом."""

    def test_403_not_accepted(self) -> None:
        """Раньше такой ответ считался провалом, теперь — «непонятно».

        Главное: успехом считать нельзя, иначе инструмент пойдёт
        откликаться с непройденной капчей.
        """
        instance = flow([FakeResponse(403)])
        result = instance.submit("word", key="k")
        assert not result.accepted
        assert result.reason == "http_403"

    def test_500_not_accepted(self) -> None:
        instance = flow([FakeResponse(500)])
        assert not instance.submit("word", key="k").accepted

    def test_200_with_garbage_body_accepted(self) -> None:
        """Мусор вместо JSON — это не отказ, а отсутствие маркера."""
        instance = flow([FakeResponse(200, body=b"<html>oops</html>")])
        assert instance.submit("word", key="k").accepted


class TestSubmitOrder:
    """Отправка идет по правильному адресу и с правильными полями."""

    def test_submit_sends_expected_params(self) -> None:
        instance = flow([FakeResponse(302)])
        instance.submit("two words", key="abc-123")
        _, url, kwargs = instance.session.calls[0]
        assert url == "https://hh.ru/account/captcha"
        params = kwargs["params"]
        assert params["captchaText"] == "two words"
        assert params["captchaKey"] == "abc-123"
        assert params["captchaState"] == STATE
        assert params["failurl"] == CAPTCHA_URL
        assert params["backurl"] == "https://hh.ru/"

    def test_submit_does_not_follow_redirects(self) -> None:
        """Редирект и есть ответ hh.ru,followять его нельзя."""
        instance = flow([FakeResponse(302)])
        instance.submit("word", key="k")
        _, _, kwargs = instance.session.calls[0]
        assert kwargs["allow_redirects"] is False

    def test_submit_sends_ajax_headers(self) -> None:
        instance = flow([FakeResponse(302)])
        instance.submit("word", key="k")
        _, _, kwargs = instance.session.calls[0]
        headers = kwargs["headers"]
        assert headers["X-Xsrftoken"] == "87ca0842token"
        assert headers["X-Requested-With"] == "XMLHttpRequest"
        assert headers["Referer"].startswith(
            "https://hh.ru/account/captcha?"
        )

    def test_submit_without_xsrf_raises(self) -> None:
        session = FakeSession([FakeResponse(302)])
        session.cookies = requests.cookies.RequestsCookieJar()
        instance = CaptchaFlow(session, CAPTCHA_URL)
        with pytest.raises(CaptchaError, match="_xsrf"):
            instance.submit("word", key="k")


class TestFetch:
    """Получение картинки нужного языка."""

    def picture_session(self) -> FakeSession:
        return FakeSession(
            [
                FakeResponse(200, body=b'{"key": "abc-123"}'),
                FakeResponse(200, body=b"\x89PNG-bytes"),
            ]
        )

    def test_fetch_asks_language_in_post(self) -> None:
        """Язык картинки задаёт lang у POST /captcha.

        Не ссылка на страницу капчи и не кука session_language: страница
        сама запрашивает картинку на своём языке, поэтому без явного
        lang картинка приходит кириллической.
        """
        session = self.picture_session()
        session.cookies = cookie_jar()
        instance = CaptchaFlow(session, CAPTCHA_URL, language="ru")
    
        instance.fetch()

        method, url, kwargs = session.calls[0]
        assert method == "POST"
        assert url == "https://hh.ru/captcha"
        assert kwargs["params"] == {"lang": "RU"}

    def test_fetch_default_language_is_latin(self) -> None:
        assert CAPTCHA_LANGUAGE_DEFAULT == "en"
        session = self.picture_session()
        session.cookies = cookie_jar()
        instance = CaptchaFlow(session, CAPTCHA_URL)

        instance.fetch()

        assert session.calls[0][2]["params"] == {"lang": "EN"}

    def test_fetch_returns_key_and_bytes(self) -> None:
        session = self.picture_session()
        session.cookies = cookie_jar()
        instance = CaptchaFlow(session, CAPTCHA_URL)

        image = instance.fetch()

        assert image.key == "abc-123"
        assert image.image == b"\x89PNG-bytes"
        assert session.calls[1][0] == "GET"
        assert session.calls[1][1] == "https://hh.ru/captcha/picture"
        assert session.calls[1][2]["params"] == {"key": "abc-123"}

    def test_fetch_without_key_raises(self) -> None:
        session = FakeSession([FakeResponse(200, body=b'{"nokey": 1}')])
        session.cookies = cookie_jar()
        instance = CaptchaFlow(session, CAPTCHA_URL)

        with pytest.raises(CaptchaError, match="ключ"):
            instance.fetch()

    def test_fetch_empty_picture_raises(self) -> None:
        session = FakeSession(
            [FakeResponse(200, body=b'{"key": "k"}'), FakeResponse(200)]
        )
        session.cookies = cookie_jar()
        instance = CaptchaFlow(session, CAPTCHA_URL)

        with pytest.raises(CaptchaError, match="Картинка"):
            instance.fetch()

    def test_each_fetch_gives_fresh_picture(self) -> None:
        """Обновление картинки не требует кнопки: каждый вызов новый."""
        session = FakeSession(
            [
                FakeResponse(200, body=b'{"key": "key-1"}'),
                FakeResponse(200, body=b"PNG-1"),
                FakeResponse(200, body=b'{"key": "key-2"}'),
                FakeResponse(200, body=b"PNG-2"),
            ]
        )
        session.cookies = cookie_jar()
        instance = CaptchaFlow(session, CAPTCHA_URL)

        first = instance.fetch()
        second = instance.fetch()

        assert (first.key, first.image) == ("key-1", b"PNG-1")
        assert (second.key, second.image) == ("key-2", b"PNG-2")


class TestRegionalOrigin:
    """Страница капчи может увести нас на региональный домен."""

    def test_prime_remembers_regional_domain(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    200, url="https://ekaterinburg.hh.ru/account/captcha"
                )
            ]
        )
        session.cookies = cookie_jar()
        instance = CaptchaFlow(session, CAPTCHA_URL)

        instance.prime()

        assert instance.origin == "https://ekaterinburg.hh.ru"

    def test_answered_on_where_page_landed(self) -> None:
        """Отвечать надо туда же, куда привела страница капчи."""
        session = FakeSession(
            [
                FakeResponse(
                    200, url="https://ekaterinburg.hh.ru/account/captcha"
                ),
                FakeResponse(302),
            ]
        )
        session.cookies = cookie_jar()
        instance = CaptchaFlow(session, CAPTCHA_URL)

        instance.prime()
        instance.submit("word", key="k")

        method, url, _ = session.calls[1]
        assert method == "POST"
        assert url == "https://ekaterinburg.hh.ru/account/captcha"

    def test_regional_redirect_back_is_still_rejection(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    200, url="https://ekaterinburg.hh.ru/account/captcha"
                ),
                redirect("https://ekaterinburg.hh.ru/account/login"),
            ]
        )
        session.cookies = cookie_jar()
        instance = CaptchaFlow(session, CAPTCHA_URL)

        instance.prime()
        result = instance.submit("word", key="k")

        assert not result.accepted

    def test_prime_keeps_origin_when_stays_on_hh(self) -> None:
        session = FakeSession([FakeResponse(200)])
        session.cookies = cookie_jar()
        instance = CaptchaFlow(session, CAPTCHA_URL)

        instance.prime()

        assert instance.origin == "https://hh.ru"


class TestConstruction:
    """Разбор ссылки, которую hh.ru присылает в ответе 403."""

    def test_state_is_required(self) -> None:
        session = FakeSession([])
        session.cookies = cookie_jar()
        with pytest.raises(CaptchaError, match="state"):
            CaptchaFlow(session, "https://hh.ru/account/captcha")

    def test_backurl_taken_from_link(self) -> None:
        session = FakeSession([])
        session.cookies = cookie_jar()
        instance = CaptchaFlow(
            session,
            CAPTCHA_URL + "&backurl=https%3A%2F%2Fhh.ru%2Fvacancy%2F1",
        )
        assert instance.backurl == "https://hh.ru/vacancy/1"

    def test_backurl_can_be_overridden(self) -> None:
        """Свой backurl позволяет отличить принятие от отказа точнее."""
        session = FakeSession([])
        session.cookies = cookie_jar()
        instance = CaptchaFlow(
            session, CAPTCHA_URL, backurl="https://hh.ru/?passed=1"
        )
        assert instance.backurl == "https://hh.ru/?passed=1"

    def test_blank_language_falls_back_to_default(self) -> None:
        session = FakeSession([])
        session.cookies = cookie_jar()
        assert CaptchaFlow(session, CAPTCHA_URL, language="  ").language == "EN"