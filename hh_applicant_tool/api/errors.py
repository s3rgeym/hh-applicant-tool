# from copy import deepcopy
from typing import Any

from requests import Request, Response
from requests.adapters import CaseInsensitiveDict

__all__ = (
    "ApiError",
    "BadGateway",
    "BadRequest",
    "ClientError",
    "Forbidden",
    "InternalServerError",
    "Redirect",
    "ResourceNotFound",
)


class ApiError(Exception):
    def __init__(self, response: Response, data: dict[str, Any]) -> None:
        self._response = response
        self._raw = data

    @property
    def data(self) -> dict:
        return self._raw

    @property
    def request(self) -> Request:
        return self._response.request

    @property
    def status_code(self) -> int:
        return self._response.status_code

    @property
    def response_headers(self) -> CaseInsensitiveDict:
        return self._response.headers

#     def __getattr__(self, name: str) -> Any:
#         try:
#             return self._raw[name]
#         except KeyError as ex:
#             raise AttributeError(name) from ex

    def __str__(self) -> str:
        return str(self._raw)


class Redirect(ApiError):
    pass


class ClientError(ApiError):
    pass


class BadRequest(ClientError):
    @property
    def limit_exceeded(self) -> bool:
        return any(x["value"] == "limit_exceeded" for x in self._raw["errors"])


class Forbidden(ClientError):
    pass


class ResourceNotFound(ClientError):
    pass


class InternalServerError(ApiError):
    pass


# По всей видимости, прокси возвращает, когда их бекенд на Java падает
# {'description': 'Bad Gateway', 'errors': [{'type': 'bad_gateway'}], 'request_id': '<md5 хеш>'}
class BadGateway(InternalServerError):
    pass
