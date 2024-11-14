import os
import json
from urllib.parse import urljoin
import requests
from typing import Optional, Dict, Any
import logging
import base64
from functools import partialmethod

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
        *,
        session: Optional[requests.Session] = None,
        user_agent: str = "Mozilla/5.0 (HHApplicantTelemetry/1.0)",
        proxies: dict | None = None,
    ) -> None:
        self.server_address = os.getenv(
            "TELEMETRY_SERVER", server_address or self.server_address
        )
        self.session = session or requests.Session()
        self.user_agent = user_agent
        self.proxies = proxies

    def request(
        self,
        method: str,
        endpoint: str,
        data: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        method = method.upper()
        url = urljoin(self.server_address, endpoint)
        has_body = method in ["POST", "PUT", "PATCH"]
        try:
            response = self.session.request(
                method,
                url,
                headers={"User-Agent": self.user_agent},
                proxies=self.proxies,
                params=data if not has_body else None,
                json=data if has_body else None,
            )
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

    send_telemetry = partialmethod(request, "POST")
