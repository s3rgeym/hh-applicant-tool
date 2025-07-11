from __future__ import annotations

import json
import logging
import os
import time
import warnings
from functools import partialmethod
from typing import Any, Dict, Optional
from urllib.parse import urljoin
import requests
from .utils import Config

# Сертификат на сервере давно истек, но его обновлять мне лень...
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

logger = logging.getLogger(__package__)


class TelemetryError(Exception):
    """Исключение, возникающее при ошибках в работе TelemetryClient."""

    pass


class TelemetryClient:
    """Клиент для отправки телеметрии на сервер."""

    server_address: str = "https://hh-applicant-tool.mooo.com:54157/"
    default_delay: float = 0.334  # Задержка по умолчанию в секундах

    def __init__(
        self,
        telemetry_client_id: str,
        server_address: Optional[str] = None,
        *,
        session: Optional[requests.Session] = None,
        user_agent: str = "Mozilla/5.0 (HHApplicantTelemetry/1.0)",
        proxies: dict | None = None,
        delay: Optional[float] = None,
    ) -> None:
        self.send_telemetry_id = telemetry_client_id
        self.server_address = os.getenv(
            "TELEMETRY_SERVER", server_address or self.server_address
        )
        self.session = session or requests.Session()
        self.user_agent = user_agent
        self.proxies = proxies
        self.delay = delay if delay is not None else self.default_delay
        self.last_request_time = time.monotonic()  # Время последнего запроса

    def request(
        self,
        method: str,
        endpoint: str,
        data: Dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        method = method.upper()
        url = urljoin(self.server_address, endpoint)
        has_body = method in ["POST", "PUT", "PATCH"]

        # Вычисляем время, прошедшее с последнего запроса
        current_time = time.monotonic()
        time_since_last_request = current_time - self.last_request_time

        # Если прошло меньше времени, чем задержка, ждем оставшееся время
        if time_since_last_request < self.delay:
            time.sleep(self.delay - time_since_last_request)

        try:
            response = self.session.request(
                method,
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "X-Telemetry-Client-ID": self.send_telemetry_id,
                },
                proxies=self.proxies,
                params=data if not has_body else None,
                json=data if has_body else None,
                verify=False,  # Игнорирование истекшего сертификата
                **kwargs,
            )
            # response.raise_for_status()
            result = response.json()
            if 200 > response.status_code >= 300:
                raise TelemetryError(result)
            return result

        except (
            requests.exceptions.RequestException,
            json.JSONDecodeError,
        ) as ex:
            raise TelemetryError(str(ex)) from ex
        finally:
            # Обновляем время последнего запроса
            self.last_request_time = time.monotonic()

    get_telemetry = partialmethod(request, "GET")
    send_telemetry = partialmethod(request, "POST")

    @classmethod
    def create_from_config(cls, config: Config) -> "TelemetryClient":
        assert "telemetry_client_id" in config
        return cls(config["telemetry_client_id"])
