from __future__ import annotations

import dataclasses
import json
import logging
import time
from dataclasses import dataclass
from functools import partialmethod
from threading import Lock
from typing import Any, Literal
from urllib.parse import urlencode

import requests
from requests import Response, Session
import random

from ..constants import (
    ANDROID_CLIENT_ID,
    ANDROID_CLIENT_SECRET,
    USER_AGENT_TEMPLATE,
)
from ..types import AccessToken
from . import errors

__all__ = ("ApiClient", "OAuthClient")

logger = logging.getLogger(__package__)


ALLOWED_METHODS = Literal["GET", "POST", "PUT", "DELETE"]


# Thread-safe
@dataclass
class BaseClient:
    base_url: str
    _: dataclasses.KW_ONLY
    # TODO: сделать генерацию User-Agent'а как в приложении
    user_agent: str | None = None
    session: Session | None = None
    previous_request_time: float = 0.0
    delay: float = 0.334

    def __post_init__(self) -> None:
        self.lock = Lock()
        if not self.session:
            self.session = session = requests.session()
            session.headers.update(
                {
                    **self.additional_headers(),
                    "User-Agent": self.user_agent or self.default_user_agent(),
                }
            )
            logger.debug("Default Headers: %r", session.headers)

    def default_user_agent(self) -> str:
        return USER_AGENT_TEMPLATE % (
            random.choice(["8.0", "8.1", "9", "10", "11", "12"]),
            random.choice(
                [
                    "SM-G998B",  # Samsung Galaxy S21 Ultra
                    "Pixel 6",  # Google Pixel 6
                    "Mi 11",  # Xiaomi Mi 11
                    "OnePlus 9",  # OnePlus 9
                    "P40",  # Huawei P40
                    "LG G8",  # LG G8
                    "Xperia 1 II",  # Sony Xperia 1 II
                    "Moto G Power",  # Motorola Moto G Power
                    "HTC U12+",  # HTC U12+
                    "ROG Phone 5",  # Asus ROG Phone 5
                ]
            ),
            random.randint(88, 130),
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
        delay: float | None = None,
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
                delay := (self.delay if delay is None else delay)
                - time.monotonic()
                + self.previous_request_time
            ) > 0:
                logger.debug("wait %fs before request", delay)
                time.sleep(delay)
            has_body = method in ["POST", "PUT"]
            response = self.session.request(
                method,
                url,
                **{"data" if has_body else "params": params},
                allow_redirects=False,
            )
            try:
                # У этих лошков сервер не отдает Content-Length, а кривое API отдает пустые ответы, например, при отклике на вакансии, и мы не можем узнать содержит ли ответ тело
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
                logger.debug(
                    "%d %-6s %s",
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
        assert 300 > response.status_code >= 200
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
            case 301 | 302:
                raise errors.Redirect(response, data)
            case 400:
                raise errors.BadRequest(response, data)
            case 403:
                raise errors.Forbidden(response, data)
            case 404:
                raise errors.ResourceNotFound(response, data)
            case status if 500 > status >= 400:
                raise errors.ClientError(response, data)
            case 502:
                raise errors.BadGateway(response, data)
            case status if status >= 500:
                raise errors.InternalServerError(response, data)


@dataclass
class OAuthClient(BaseClient):
    client_id: str = ANDROID_CLIENT_ID
    client_secret: str = ANDROID_CLIENT_SECRET
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
        return self.post("/token", params)

    def refresh_access(self, refresh_token: str) -> AccessToken:
        # refresh_token можно использовать только один раз и только по истечению срока действия access_token.
        return self.post(
            "/token", grant_type="refresh_token", refresh_token=refresh_token
        )


@dataclass
class ApiClient(BaseClient):
    # Например, для просмотра информации о компании токен не нужен
    access_token: str | None = None
    refresh_token: str | None = None
    _: dataclasses.KW_ONLY
    base_url: str = "https://api.hh.ru/"
    # oauth_client: OAuthClient | None = None

    # def __post_init__(self) -> None:
    #     super().__post_init__()
    #     self.oauth_client = self.oauth_client or OAuthClient(
    #         session=self.session
    #     )

    def additional_headers(
        self,
    ) -> dict[str, str]:
        return (
            {"Authorization": f"Bearer {self.access_token}"}
            if self.access_token
            else {}
        )

    # def refresh_access(self) -> AccessToken:
    #     tok = self.oauth_client.refresh_access(self.refresh_token)
    #     (
    #         self.access_token,
    #         self.refresh_access,
    #     ) = (
    #         tok["access_token"],
    #         tok["refresh_token"],
    #     )
    #     return tok
