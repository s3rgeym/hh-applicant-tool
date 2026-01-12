from __future__ import annotations

from functools import cached_property
from typing import Any, Type

from requests import Request, Response
from requests.adapters import CaseInsensitiveDict

__all__ = (
    "BadResponse",
    "ApiError",
    "BadGateway",
    "BadRequest",
    "ClientError",
    "Forbidden",
    "InternalServerError",
    "Redirect",
    "ResourceNotFound",
)


class BadResponse(Exception):
    pass


class ApiError(BadResponse):
    def __init__(self, response: Response, data: dict[str, Any]) -> None:
        self._response = response
        self._data = data

    @property
    def data(self) -> dict:
        return self._data

    @property
    def request(self) -> Request:
        return self._response.request

    @property
    def status_code(self) -> int:
        return self._response.status_code

    @property
    def response_headers(self) -> CaseInsensitiveDict:
        return self._response.headers

    @property
    def message(self) -> str:
        return (
            self._data.get("error_description")
            or self._data.get("description")
            or str(self._data)
        )

    #     def __getattr__(self, name: str) -> Any:
    #         try:
    #             return self._raw[name]
    #         except KeyError as ex:
    #             raise AttributeError(name) from ex

    def __str__(self) -> str:
        return self.message

    @staticmethod
    def has_error_value(value: str, data: dict) -> bool:
        return any(v.get("value") == value for v in data.get("errors", []))

    @classmethod
    def raise_for_status(
        cls: Type[ApiError], response: Response, data: dict
    ) -> None:
        match response.status_code:
            case status if 300 <= status <= 308:
                raise Redirect(response, data)
            case 400:
                if cls.has_error_value("limit_exceeded", data):
                    raise LimitExceeded(response, data)
                raise BadRequest(response, data)
            case 403:
                if cls.has_error_value("captcha_required", data):
                    raise CaptchaRequired(response, data)
                raise Forbidden(response, data)
            case 404:
                raise ResourceNotFound(response, data)
            case status if 500 > status >= 400:
                raise ClientError(response, data)
            case 502:
                raise BadGateway(response, data)
            case status if status >= 500:
                raise InternalServerError(response, data)


class Redirect(ApiError):
    pass


class ClientError(ApiError):
    pass


class BadRequest(ClientError):
    pass


class LimitExceeded(ClientError):
    pass


class Forbidden(ClientError):
    pass


class CaptchaRequired(ClientError):
    @cached_property
    def captcha_url(self) -> str:
        return next(
            filter(
                lambda v: v["value"] == "captcha_required",
                self._data["errors"],
            ),
            {},
        ).get("captcha_url")

    @property
    def message(self) -> str:
        return f"Captcha required: {self.captcha_url}"


class ResourceNotFound(ClientError):
    pass


class InternalServerError(ApiError):
    pass


# По всей видимости, прокси возвращает, когда их бекенд на Java падает
# {'description': 'Bad Gateway', 'errors': [{'type': 'bad_gateway'}], 'request_id': '<md5 хеш>'}
class BadGateway(InternalServerError):
    pass
