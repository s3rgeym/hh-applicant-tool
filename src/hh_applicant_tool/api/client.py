from __future__ import annotations

import dataclasses
import logging
import time
from dataclasses import dataclass, field
from functools import cached_property
from threading import Lock
from typing import Any, Callable, Literal, TypeVar
from urllib.parse import urlencode, urljoin

import requests

from . import errors
from .client_keys import (
    ANDROID_CLIENT_ID,
    ANDROID_CLIENT_SECRET,
)
from .datatypes import AccessToken
from .user_agent import generate_android_useragent

__all__ = ("ApiClient", "OAuthClient")

HH_API_URL = "https://api.hh.ru"
HH_OAUTH_URL = "https://hh.ru/oauth/"
DEFAULT_DELAY = 0.345
DEFAULT_CAPTCHA_COOLDOWN = 5.0
MAX_RETRIES = 3
MAX_CAPTCHA_RETRIES = 5

AllowedMethods = Literal[
    "GET",
    "POST",
    "PUT",
    "DELETE",
    "get",
    "post",
    "put",
    "delete",
]

T = TypeVar("T")

logger = logging.getLogger("hh-applicant-tool")


# Thread-safe
@dataclass
class BaseClient:
    base_url: str
    _: dataclasses.KW_ONLY
    delay: float | None = None
    max_retries: int | None = None
    session: requests.Session | None = None
    user_agent: str | None = None

    _previous_request_time: float = field(default=0.0, init=False)
    _lock: Lock = field(
        default_factory=Lock, init=False, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        self.delay = self.delay or DEFAULT_DELAY
        self.max_retries = self.max_retries or MAX_RETRIES
        self.user_agent = self.user_agent or generate_android_useragent()
        class_name = self.__class__.__name__
        logger.debug(f"{class_name} User-Agent: {self.user_agent}")

        if not self.session:
            logger.debug(f"Сreate new session for {class_name}")
            self.session = requests.session()

    @property
    def proxies(self):
        return self.session.proxies

    def _default_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
            "X-HH-App-Active": "true",
        }

    def _wait_for_delay(self, delay: float | None = None) -> None:
        """Выдерживает паузу между запросами.

        На серваке какая-то анти-DDOS система, поэтому между запросами
        должно пройти не меньше `delay` секунд (по умолчанию self.delay).
        Вызывать нужно под self.lock, т.к. читается _previous_request_time.
        """
        wait = (
            (self.delay if delay is None else delay)
            - time.monotonic()
            + self._previous_request_time
        )
        if wait > 0:
            logger.debug("wait %fs before request", wait)
            time.sleep(wait)

    def request(
        self,
        method: AllowedMethods,
        endpoint: str,
        params: dict[str, Any] | None = None,
        *,
        delay: float | None = None,
        as_json: bool = False,
        **kwargs: Any,
    ) -> T:
        method = method.upper()
        params = dict(params or {})
        params.update(kwargs)
        url = self.resolve_url(endpoint)

        if method in ("POST", "PUT"):
            payload = {"json" if as_json else "data": params}
        else:
            payload = {"params": params}

        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            with self._lock:
                self._wait_for_delay(delay)
                logger.debug(
                    f"({attempt}/{self.max_retries}) {method} {url} {params!r}",
                )
                try:
                    # Заголовки собираются на каждой попытке, чтобы
                    # подхватывать обновлённый access token.
                    response = self.session.request(
                        method,
                        url,
                        headers=self._default_headers(),
                        allow_redirects=False,
                        **payload,
                    )
                except requests.ConnectionError as ex:
                    logger.warning(
                        "(%d/%d) connection error: %s %s: %s",
                        attempt,
                        self.max_retries,
                        method,
                        url,
                        ex,
                    )
                    last_exc = ex
                    continue
                finally:
                    self._previous_request_time = time.monotonic()

                logger.debug("%s %s %d", method, url, response.status_code)

                # У этих лошков сервер не отдает Content-Length, а кривое API
                # отдает пустые ответы, например, при отклике на вакансии,
                # и мы не можем узнать содержит ли ответ тело
                # 'Server': 'ddos-guard'
                # ...
                # 'Transfer-Encoding': 'chunked'
                try:
                    rv = response.json() if response.text else {}
                except ValueError as ex:  # включая JSONDecodeError
                    raise errors.BadResponse(
                        f"Can't decode JSON: {method} {url} "
                        f"({response.status_code})"
                    ) from ex

            errors.ApiError.raise_for_status(response, rv)
            return rv

        # Все попытки закончились ошибками соединения
        assert last_exc is not None
        raise last_exc

    def get(self, *args, **kwargs) -> T:
        return self.request("GET", *args, **kwargs)

    def post(self, *args, **kwargs) -> T:
        return self.request("POST", *args, **kwargs)

    def put(self, *args, **kwargs) -> T:
        return self.request("PUT", *args, **kwargs)

    def delete(self, *args, **kwargs) -> T:
        return self.request("DELETE", *args, **kwargs)

    def resolve_url(self, url: str) -> str:
        return urljoin(self.base_url, url.lstrip("/"))


@dataclass
class OAuthClient(BaseClient):
    client_id: str | None = None
    client_secret: str | None = None
    _: dataclasses.KW_ONLY
    base_url: str = HH_OAUTH_URL
    state: str = ""
    scope: str = ""
    redirect_uri: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        self.client_id = self.client_id or ANDROID_CLIENT_ID
        self.client_secret = self.client_secret or ANDROID_CLIENT_SECRET

    def authorize_url(self, **kwargs: Any) -> str:
        params = dict(
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
            response_type="code",
            scope=self.scope,
            state=self.state,
            **kwargs,
        )
        query = urlencode({k: v for k, v in params.items() if v})
        return self.resolve_url(f"/authorize?{query}")

    def request_access_token(
        self, endpoint: str, params: dict[str, Any] | None = None, **kw: Any
    ) -> AccessToken:
        tok = self.post(endpoint, params, **kw)
        return {
            "access_token": tok.get("access_token"),
            "refresh_token": tok.get("refresh_token"),
            "access_expires_at": int(time.time()) + tok.pop("expires_in", 0),
        }

    def authenticate(self, code: str) -> AccessToken:
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
        }
        return self.request_access_token("/token", params)

    def refresh_access_token(self, refresh_token: str) -> AccessToken:
        # refresh_token можно использовать только один раз и только по
        # истечению срока действия access_token.
        return self.request_access_token(
            "/token",
            grant_type="refresh_token",
            refresh_token=refresh_token,
        )


@dataclass
class ApiClient(BaseClient):
    # Например, для просмотра информации о компании токен не нужен
    access_token: str | None = None
    refresh_token: str | None = None
    access_expires_at: int = 0
    _: dataclasses.KW_ONLY
    client_id: str | None = None
    client_secret: str | None = None
    base_url: str = HH_API_URL
    captcha_handler: Callable[[str], bool] | None = None
    captcha_cooldown: float | None = None
    max_captcha_attempts: int | None = None

    _captcha_lock: Lock = field(
        default_factory=Lock, init=False, compare=False, repr=False
    )
    _refresh_lock: Lock = field(
        default_factory=Lock, init=False, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        self.captcha_cooldown = (
            self.captcha_cooldown or DEFAULT_CAPTCHA_COOLDOWN
        )
        self.max_captcha_attempts = (
            self.max_captcha_attempts or MAX_CAPTCHA_RETRIES
        )
        return super().__post_init__()

    @property
    def is_access_expired(self) -> bool:
        return time.time() >= (self.access_expires_at or 0)

    @cached_property
    def oauth_client(self) -> OAuthClient:
        return OAuthClient(
            client_id=self.client_id,
            client_secret=self.client_secret,
            user_agent=self.user_agent,
            session=self.session,
        )

    def _default_headers(
        self,
    ) -> dict[str, str]:
        headers = super()._default_headers()
        if not self.access_token:
            return headers
        # Это очень интересно, что access token'ы начинаются с USER, т.е. API может содержать какую-то уязвимость, связанную с этим
        assert self.access_token.startswith("USER")
        return headers | {"Authorization": f"Bearer {self.access_token}"}

    def request(
        self,
        method,
        endpoint,
        params=None,
        delay=None,
        as_json=False,
        *,
        captcha_cooldown=None,
        max_captcha_attempts=None,
        **kwargs,
    ):
        captcha_cooldown = captcha_cooldown or self.captcha_cooldown
        max_captcha_attempts = max_captcha_attempts or self.max_captcha_attempts
        refreshed = False
        while True:
            try:
                return super().request(
                    method,
                    endpoint,
                    params,
                    delay=delay,
                    as_json=as_json,
                    **kwargs,
                )
            # Глобальный перехват ошибок капчи
            except errors.CaptchaRequired as ex:
                if not self.captcha_handler:
                    raise
                # Одновременно капчу несколько потоков решать не должны
                with self._captcha_lock:
                    attempts = max_captcha_attempts
                    while attempts:
                        logger.debug(
                            f"({max_captcha_attempts - attempts + 1}/{max_captcha_attempts}) handle captcha: {ex.captcha_url}"
                        )
                        accepted = self.captcha_handler(ex.captcha_url)
                        if accepted:
                            logger.info("captcha accepted!")
                            break
                        attempts -= 1
                    if accepted:
                        logger.debug(f"captcha cooldown: {captcha_cooldown}")
                        time.sleep(captcha_cooldown)
                        continue
                raise
            except errors.Forbidden:
                if (
                    refreshed
                    or not self.refresh_token
                    or not self.is_access_expired
                ):
                    raise
                with self._refresh_lock:
                    # Тоже может в свою очередь кинуть 400 или 403, если refresh_token недействителен
                    try:
                        self.refresh_access_token()
                    # Ошибка слишком общая
                    except errors.ApiError:
                        self.reset_tokens()
                        raise
                    refreshed = True

    def reset_tokens(self) -> None:
        self.access_token = None
        self.refresh_token = None
        self.access_expires_at = 0

    def handle_access_token(self, token: AccessToken) -> None:
        for name in ("access_token", "refresh_token", "access_expires_at"):
            if name in token and hasattr(self, name):
                setattr(self, name, token[name])

    def refresh_access_token(self) -> None:
        if not self.refresh_token:
            raise ValueError("Refresh token required.")
        token = self.oauth_client.refresh_access_token(self.refresh_token)
        self.handle_access_token(token)

    def get_access_token(self) -> AccessToken:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "access_expires_at": self.access_expires_at,
        }
