import logging
from copy import deepcopy

import requests

logger = logging.getLogger(__package__)


class BlackboxError(Exception):
    pass


class BlackboxChat:
    chat_endpoint: str = "https://www.blackbox.ai/api/chat"

    def __init__(
        self,
        session_id: str,
        chat_payload: dict,
        proxies: dict[str, str] = {},
        session: requests.Session | None = None,
    ):
        self.session_id = session_id
        self.chat_payload = chat_payload
        self.proxies = proxies
        self.session = session or requests.session()

    def default_headers(self) -> dict[str, str]:
        return {
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
            "Content-Type": "application/json",
            "Origin": "https://www.blackbox.ai",
            "Priority": "u=0",
            "Referer": "https://www.blackbox.ai/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }

    def send_message(self, message: str) -> str:
        payload = deepcopy(self.chat_payload)
        payload["messages"].append(
            {**payload["messages"][0], "content": message}
        )

        try:
            response = self.session.post(
                self.chat_endpoint,
                json=payload,
                cookies={"sessionId": self.session_id},
                headers=self.default_headers(),
                proxies=self.proxies,
            )
            return response.text
        except requests.exceptions.RequestException as ex:
            raise BlackboxError(str(ex)) from ex
