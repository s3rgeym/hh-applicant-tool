from __future__ import annotations

import dataclasses
import json
import logging
import time
from dataclasses import dataclass, field
from functools import cached_property
from threading import Lock
from typing import Any, Callable, Literal, TypeVar
from urllib.parse import urlencode, urljoin

import requests
from requests import PreparedRequest, Request, Session

from hh_applicant_tool.api.user_agent import generate_android_useragent

from . import errors
from .client_keys import (
    ANDROID_CLIENT_ID,
    ANDROID_CLIENT_SECRET,
)
from .datatypes import AccessToken

__all__ = ("ApiClient", "OAuthClient")

HH_API_URL = "https://api.hh.ru/"
HH_OAUTH_URL = "https://hh.ru/oauth/"
DEFAULT_DELAY = 0.345
DEFAULT_CAPTCHA_COOLDOWN = 3.0

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


logger = logging.getLogger(__package__)


# Thread-safe
@dataclass
class BaseClient:
    base_url: str
    _: dataclasses.KW_ONLY
    user_agent: str | None = None
    session: Session | None = None
    delay: float | None = None
    captcha_handler: Callable[[str], bool] | None = None
    captcha_cooldown: float | None = None

    _previous_request_time: float = field(default=0.0, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)
    _captcha_lock: Lock = field(default_factory=Lock, init=False)

    def __post_init__(self) -> None:
        assert self.base_url.endswith("/"), "base_url must ends with /"
        self.delay = self.delay or DEFAULT_DELAY
        self.captcha_cooldown = (
            self.captcha_cooldown or DEFAULT_CAPTCHA_COOLDOWN
        )
        self.user_agent = self.user_agent or generate_android_useragent()

        # logger.debug(f"user agent: {self.user_agent}")

        if not self.session:
            logger.debug("create new session")
            self.session = requests.session()

    @property
    def proxies(self):
        return self.session.proxies

    def _default_headers(self) -> dict[str, str]:
        return {
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
        # # Не знаю насколько это "правильно"
        # assert method.upper() in AllowedMethods.__args__, (
        #     f"Method unknown or not allowed: {method!r}"
        # )
        method = method.upper()
        params = dict(params or {})
        params.update(kwargs)
        url = self.resolve_url(endpoint)
        has_body = method in ["POST", "PUT"]
        payload = {["data", "json"][as_json] if has_body else "params": params}
        req = Request(
            method,
            url,
            headers=self._default_headers(),
            **payload,
        )
        return self.send(req, delay=delay)

    def send(
        self,
        request: Request | PreparedRequest,
        *,
        delay: float | None = None,
    ) -> T:
        """Отправляет уже готовый Request/PreparedRequest.

        Нужен для повторной отправки запроса после ошибки капчи.

        Как-то так:

            BaseClient.send(ex.request)
        """
        if isinstance(request, Request):
            prepared = self.session.prepare_request(request)
        else:
            prepared = request

        while True:
            with self._lock:
                self._wait_for_delay(delay)

                # session.send, в отличие от session.request, сам не учитывает
                # proxies/verify/cert из окружения, поэтому подмешиваем их вручную
                settings = self.session.merge_environment_settings(
                    prepared.url, {}, None, None, None
                )
                response = self.session.send(
                    prepared,
                    allow_redirects=False,
                    **settings,
                )
                try:
                    # У этих лошков сервер не отдает Content-Length, а кривое API
                    # отдает пустые ответы, например, при отклике на вакансии,
                    # и мы не можем узнать содержит ли ответ тело
                    # 'Server': 'ddos-guard'
                    # ...
                    # 'Transfer-Encoding': 'chunked'
                    try:
                        rv = response.json() if response.text else {}
                    except json.JSONDecodeError as ex:
                        raise errors.BadResponse(
                            f"Can't decode JSON: {prepared.method} {prepared.url} "
                            f"({response.status_code})"
                        ) from ex
                finally:
                    logger.debug(
                        "%d %s %s with body: %.1000s",
                        response.status_code,
                        prepared.method,
                        prepared.url,
                        prepared.body or "-",
                    )
                    self._previous_request_time = time.monotonic()

            try:
                errors.ApiError.raise_for_status(response, rv)
            except errors.CaptchaRequired as ex:
                if not callable(self.captcha_handler):
                    raise
                with self._captcha_lock:
                    if not self.captcha_handler(ex.captcha_url):
                        raise
                    time.sleep(self.captcha_cooldown)
                continue

            if not (200 <= response.status_code < 300):
                raise errors.BadResponse(
                    f"Unexpected status code for {prepared.method} "
                    f"{prepared.url}: {response.status_code}"
                )
            return rv

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

    @property
    def authorize_url(self) -> str:
        params = dict(
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
            response_type="code",
            scope=self.scope,
            state=self.state,
        )
        params_qs = urlencode({k: v for k, v in params.items() if v})
        return self.resolve_url(f"/authorize?{params_qs}")

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
            captcha_handler=self.captcha_handler,
            captcha_cooldown=self.captcha_cooldown,
        )

    def _default_headers(
        self,
    ) -> dict[str, str]:
        headers = super()._default_headers()
        if not self.access_token:
            return headers
        # Это очень интересно, что access token'ы начинаются с USER, т.е. API может содержать какую-то уязвимость, связанную с этим
        assert self.access_token.startswith("USER")
        return headers | {"authorization": f"Bearer {self.access_token}"}

    # Реализовано автоматическое обновление токена
    def request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        delay: float | None = None,
        as_json: bool = False,
        **kwargs: Any,
    ) -> T:
        def do_request():
            return BaseClient.request(
                self,
                method,
                endpoint,
                params,
                delay=delay,
                as_json=as_json,
                **kwargs,
            )

        try:
            return do_request()
        # TODO: добавить класс для ошибок типа AccessTokenExpired
        except errors.Forbidden as ex:
            if not self.is_access_expired or not self.refresh_token:
                raise ex
            logger.info("try to refresh access_token")
            # Пробуем обновить токен
            self.refresh_access_token()
            # И повторно отправляем запрос
            return do_request()

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
