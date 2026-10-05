from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

from ..constants import DEFAULT_CAPTCHA_LANGUAGE

logger = logging.getLogger(__package__)

__all__ = (
    "REASON_ACCEPTED",
    "REASON_REJECTED",
    "REASON_UNKNOWN",
    "CaptchaError",
    "CaptchaFlow",
    "CaptchaImage",
    "CaptchaResult",
)

# Латиница читается заметно лучше кириллицы, поэтому по умолчанию
# просим английскую картинку
CAPTCHA_LANGUAGE_DEFAULT = DEFAULT_CAPTCHA_LANGUAGE

DEFAULT_ORIGIN = "https://hh.ru"

# Куда отправляет hh.ru после принятой капчи, если в ссылке не было
# своего backurl
DEFAULT_BACKURL = "https://hh.ru/"

# Сюда hh.ru отправляет, когда капчу не принял или сессия мёртвая.
# Редирект на любой другой адрес ответом считается
FAIL_PATHS = ("/account/captcha", "/account/login")

REASON_ACCEPTED = "accepted"
REASON_REJECTED = "rejected"
REASON_UNKNOWN = "unknown"

DEFAULT_TIMEOUT = 15


class CaptchaError(Exception):
    """С запросом к капче что-то не так: сеть, код ответа, формат."""


@dataclass(frozen=True)
class CaptchaImage:
    key: str
    image: bytes


@dataclass(frozen=True)
class CaptchaResult:
    """Итог отправки ответа.

    ok бывает только при REASON_ACCEPTED. REASON_UNKNOWN означает, что
    hh.ru не дал однозначного сигнала: такой результат нельзя считать
    ни успехом, ни отказом, иначе мы либо потеряем вакансию, либо
    пойдём откликаться с непройденной капчей.
    """

    ok: bool
    reason: str

    @property
    def accepted(self) -> bool:
        return self.reason == REASON_ACCEPTED

    @property
    def rejected(self) -> bool:
        return self.reason == REASON_REJECTED

    @property
    def unknown(self) -> bool:
        return self.reason == REASON_UNKNOWN


class CaptchaFlow:
    """Прямой протокол капчи hh.ru, без браузера.

    Порядок запросов проверен на живых капчах 2026-10-03:

        GET  /account/captcha?state=…&backurl=…  -> куки DDoS-Guard и _xsrf
        POST /captcha?lang=EN                    -> {"key": "..."}
        GET  /captcha/picture?key=…              -> PNG
        POST /account/captcha?captchaText=…&…    -> 302 либо JSON с isBot

    Язык картинки задаёт lang у POST /captcha. Ни ссылка на страницу
    капчи, ни кука session_language на него не действуют: страница
    отдаёт картинку на языке, который запрашивает сама.

    Сессия одна на весь флоу и она же аккаунтная. Это обязательно:
    картинка, ответ и последующий отклик должны идти одним cookie jar,
    иначе hh.ru не признает капчу решённой.
    """

    def __init__(
        self,
        session: requests.Session,
        captcha_url: str,
        *,
        language: str = CAPTCHA_LANGUAGE_DEFAULT,
        backurl: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        parsed = urlsplit(captcha_url)
        query = parse_qs(parsed.query)

        state = (query.get("state") or [""])[0]
        if not state:
            raise CaptchaError("hh.ru не передал state в ссылке на капчу")

        self._session = session
        self.state = state
        self.challenge_url = captcha_url
        self.backurl = (
            backurl or (query.get("backurl") or [DEFAULT_BACKURL])[0]
        )
        self.language = (language or "").strip().upper()
        if not self.language:
            self.language = CAPTCHA_LANGUAGE_DEFAULT.upper()
        self.timeout = timeout
        if parsed.netloc:
            self._origin = f"{parsed.scheme or 'https'}://{parsed.netloc}"
        else:
            self._origin = DEFAULT_ORIGIN

    # Свойства, нужные вызывающему коду и тестам

    @property
    def origin(self) -> str:
        return self._origin

    @property
    def session(self) -> requests.Session:
        return self._session

    # Внутреннее

    def _referer(self) -> str:
        """Ссылка на страницу капчи: hh.ru проверяет её у XHR-запросов."""
        _, _, query = self.challenge_url.partition("?")
        if not query:
            return f"{self._origin}/account/captcha"
        return f"{self._origin}/account/captcha?{query}"

    def _xsrf(self) -> str:
        for cookie in self._session.cookies:
            if cookie.name == "_xsrf":
                return cookie.value or ""
        return ""

    def _ajax_headers(self) -> dict[str, str]:
        xsrf = self._xsrf()
        if not xsrf:
            raise CaptchaError("нет куки _xsrf: прогрей сессию раньше")
        return {
            "Referer": self._referer(),
            "X-Requested-With": "XMLHttpRequest",
            "X-Xsrftoken": xsrf,
            "Accept": "application/json, text/plain, */*",
        }

    def _remember_origin(self, response: requests.Response) -> None:
        """hh.ru уводит страницу капчи на региональный домен.

        Отвечать тогда надо на тот же домен, иначе POST уйдёт не туда
        и hh.ru будет перенаправлять вместо обработки ответа.
        """
        final = getattr(response, "url", "")
        if not final:
            return
        parsed = urlsplit(final)
        if parsed.path == "/account/captcha" and parsed.netloc:
            self._origin = f"{parsed.scheme}://{parsed.netloc}"

    def _is_bot(self, response: requests.Response) -> bool:
        """Вердикт hh.ru о том, что нас посчитали ботом."""
        try:
            body: Any = response.json()
        except ValueError:
            return False
        if not isinstance(body, dict):
            return False
        for field in ("hhcaptcha", "recaptcha"):
            value = body.get(field)
            if isinstance(value, dict) and value.get("isBot") is True:
                logger.debug("hh.ru пометил ответ как isBot (%s)", field)
                return True
        return False

    # Публичное

    def prime(self) -> None:
        """Открывает страницу капчи: ставит куки DDoS-Guard и _xsrf."""
        try:
            response = self._session.get(
                self.challenge_url, timeout=self.timeout, allow_redirects=True
            )
        except requests.RequestException as ex:
            raise CaptchaError(
                f"Не удалось открыть страницу капчи: {ex}"
            ) from ex

        if response.status_code != 200:
            raise CaptchaError(
                f"Страница капчи вернула HTTP {response.status_code}"
            )
        self._remember_origin(response)
        logger.debug(
            "Капча прогрета, origin=%s, _xsrf=%s",
            self._origin,
            "есть" if self._xsrf() else "НЕТ",
        )

    def fetch(self) -> CaptchaImage:
        """Просит у hh.ru новую картинку нужного языка.

        Каждый вызов выдаёт свежую картинку, поэтому отдельное
        обновление через кнопку на странице не требуется.
        """
        try:
            response = self._session.post(
                f"{self._origin}/captcha",
                params={"lang": self.language},
                headers=self._ajax_headers(),
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as ex:
            raise CaptchaError(f"Не удалось получить ключ капчи: {ex}") from ex

        if response.status_code != 200:
            raise CaptchaError(
                f"Запрос ключа капчи вернул HTTP {response.status_code}"
            )
        try:
            key = (response.json() or {}).get("key")
        except ValueError as ex:
            raise CaptchaError(f"Ответ на запрос ключа не JSON: {ex}") from ex
        if not isinstance(key, str) or not key:
            raise CaptchaError("hh.ru не вернул ключ капчи")

        try:
            picture = self._session.get(
                f"{self._origin}/captcha/picture",
                params={"key": key},
                headers={"Referer": self._referer()},
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as ex:
            raise CaptchaError(
                f"Не удалось скачать картинку капчи: {ex}"
            ) from ex

        if picture.status_code != 200 or not picture.content:
            raise CaptchaError(
                f"Картинка капчи вернула HTTP {picture.status_code}"
            )

        logger.debug(
            "Картинка капчи получена: lang=%s, key=%s, %d байт",
            self.language,
            key[:8],
            len(picture.content),
        )
        return CaptchaImage(key=key, image=picture.content)

    def submit(self, text: str, key: str) -> CaptchaResult:
        """Отправляет ответ и разбирает сигнал hh.ru.

        Правила разбора сняты с чужого реверса и подтверждены в JS
        самого hh.ru:

        * JSON с hhcaptcha.isBot или recaptcha.isBot true — отказ;
        * 302/303 на /account/captcha или /account/login — отказ;
        * любой другой 302/303, включая совсем пустой Location, —
          принято: собственный фронтенд hh.ru трактует 302 у XHR как
          завершение и уходит на backurl сам;
        * 200 без маркера isBot — принято, hh.ru так тоже подтверждает.
        """
        try:
            response = self._session.post(
                f"{self._origin}/account/captcha",
                params={
                    "captchaText": text,
                    "captchaKey": key,
                    "captchaState": self.state,
                    "backurl": self.backurl,
                    "failurl": self.challenge_url,
                },
                headers=self._ajax_headers(),
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as ex:
            raise CaptchaError(f"Не удалось отправить ответ: {ex}") from ex

        return self._interpret(response)

    def _interpret(self, response: requests.Response) -> CaptchaResult:
        if self._is_bot(response):
            return CaptchaResult(ok=False, reason="isBot")

        if response.status_code in (302, 303):
            location = response.headers.get("Location", "")
            if location:
                target = urljoin(f"{self._origin}/account/captcha", location)
                path = urlsplit(target).path
                if path in FAIL_PATHS:
                    return CaptchaResult(
                        ok=False, reason=f"redirect_{path.strip('/')}"
                    )
            return CaptchaResult(ok=True, reason=REASON_ACCEPTED)

        if response.status_code == 200:
            return CaptchaResult(ok=True, reason=REASON_ACCEPTED)

        # 4xx без isBot и без редиректа: непонятно, отвергли ответ или
        # запрос не дошёл. Успехом считать нельзя
        return CaptchaResult(ok=False, reason=f"http_{response.status_code}")

    def confirm(self) -> CaptchaResult:
        """Перечитывает страницу капчи, ничего не отправляя.

        Если hh.ru пустил нас дальше, страница ответит редиректом.
        Годится как независимая проверка после принятого ответа.
        """
        try:
            response = self._session.get(
                self.challenge_url, timeout=self.timeout, allow_redirects=False
            )
        except requests.RequestException as ex:
            raise CaptchaError(f"Не удалось перечитать капчу: {ex}") from ex

        if response.status_code in (302, 303):
            location = response.headers.get("Location", "")
            target = urljoin(f"{self._origin}/account/captcha", location)
            if urlsplit(target).path in FAIL_PATHS:
                return CaptchaResult(ok=False, reason="still_captcha")
            return CaptchaResult(ok=True, reason=REASON_ACCEPTED)

        return CaptchaResult(ok=False, reason=f"http_{response.status_code}")