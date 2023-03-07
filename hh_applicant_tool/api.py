"""https://api.hh.ru/openapi/redoc"""
from __future__ import annotations

import dataclasses
import json
import logging
import time
from copy import deepcopy
from dataclasses import dataclass
from functools import partialmethod
from threading import Lock
from typing import Any, Literal
from urllib.parse import urlencode

import requests
from requests import Response, Session

from .contsants import HHANDROID_CLIENT_ID, HHANDROID_CLIENT_SECRET
from .types import AccessToken

logger = logging.getLogger(__package__)


class ApiError(Exception):
    def __init__(self, data: dict[str, Any]) -> None:
        self._raw = deepcopy(data)

    def __getattr__(self, name: str) -> Any:
        try:
            return self._raw[name]
        except KeyError as ex:
            raise AttributeError(name) from ex

    def __str__(self) -> str:
        return str(self._raw)


class BadRequest(ApiError):
    @property
    def limit_exceeded(self) -> bool:
        return any(x["value"] == "limit_exceeded" for x in self.errors)


class Forbidden(ApiError):
    pass


class ResourceNotFound(ApiError):
    pass


# По всей видимости, прокси возвращает, когда их бекенд на Java падает
# {'description': 'Bad Gateway', 'errors': [{'type': 'bad_gateway'}], 'request_id': '<md5 хеш>'}
class BadGateaway(ApiError):
    pass


ALLOWED_METHODS = Literal["GET", "POST", "PUT", "DELETE"]


# Thread-safe
@dataclass
class BaseClient:
    base_url: str
    _: dataclasses.KW_ONLY
    # TODO: сделать генерацию User-Agent'а как в приложении
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
    session: Session | None = None
    previous_request_time: float = 0.0

    def __post_init__(self) -> None:
        self.lock = Lock()
        if not self.session:
            self.session = session = requests.session()
            session.headers.update(
                {
                    **self.additional_headers(),
                    "User-Agent": self.user_agent,
                }
            )

    def additional_headers(
        self,
    ) -> dict[str, str]:
        return {}

    def request(
        self,
        method: ALLOWED_METHODS,
        endpoint: str,
        params: dict | None = None,
        delay: float = 0.34,
        **kwargs: Any,
    ) -> dict:
        # Не знаю насколько это "правильно"
        assert method in ALLOWED_METHODS.__args__
        params = dict(params or {})
        params.update(kwargs)
        url = self.resolve_url(endpoint)
        with self.lock:
            # На серваке какая-то анти-DDOS система
            if (
                delay := delay - time.monotonic() + self.previous_request_time
            ) > 0:
                logger.debug("wait %fs", delay)
                time.sleep(delay)
            has_body = method in ["POST", "PUT"]
            response = self.session.request(
                method,
                url,
                **{"data" if has_body else "params": params},
                allow_redirects=False,
            )
            try:
                # У этих лошков сервер не отдает Content-Length, а кривое API отдает пустые ответы, например, при отклике на вакансии, и мы не можем узнать
                # 'Server': 'ddos-guard'
                # ...
                # 'Transfer-Encoding': 'chunked'
                try:
                    rv = response.json()
                except json.decoder.JSONDecodeError:
                    if response.status_code not in [201, 204]:
                        raise
                    rv = {}
            finally:
                # 100 символов максимум
                logger.debug(
                    "%d %-6s %.89s",
                    response.status_code,
                    method,
                    url
                    + (
                        "?" + urlencode(params)
                        if not has_body and params
                        else ""
                    ),
                )
                self.previous_request_time = time.monotonic()
        self.raise_for_status(response, rv)
        return rv

    get = partialmethod(request, "GET")
    post = partialmethod(request, "POST")
    put = partialmethod(request, "PUT")
    delete = partialmethod(request, "DELETE")

    def resolve_url(self, url: str) -> str:
        return (
            url
            if "://" in url
            else f"{self.base_url.rstrip('/')}/{url.lstrip('/')}"
        )

    @staticmethod
    def raise_for_status(response: Response, data: dict) -> None:
        match response.status_code:
            case 400:
                raise BadRequest(data)
            case 403:
                raise Forbidden(data)
            case 404:
                raise ResourceNotFound(data)
            case 502:
                raise BadGateaway(data)


@dataclass
class OAuthClient(BaseClient):
    client_id: str = HHANDROID_CLIENT_ID
    client_secret: str = HHANDROID_CLIENT_SECRET
    _: dataclasses.KW_ONLY
    base_url: str = "https://hh.ru/oauth"
    state: str = ""
    scope: str = ""
    redirect_uri: str = ""

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

    def authenticate(self, code: str) -> AccessToken:
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
        }
        return self.request("POST", "/token", params)

    def refresh_access(self, refresh_token: str) -> AccessToken:
        # refresh_token можно использовать только один раз и только по истечению срока действия access_token.
        return self.request(
            "POST",
            "/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )


@dataclass
class ApiClient(BaseClient):
    access_token: str
    refresh_token: str | None = None
    _: dataclasses.KW_ONLY
    base_url: str = "https://api.hh.ru/"
    # request_body_json: bool = True
    oauth_client: OAuthClient | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.oauth_client = self.oauth_client or OAuthClient(
            session=self.session
        )

    def additional_headers(
        self,
    ) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def refresh_access(self) -> None:
        tok = self.oauth_client.refresh_access(self.refresh_token)
        (
            self.access_token,
            self.refresh_access,
        ) = (
            tok["access_token"],
            tok["refresh_token"],
        )
