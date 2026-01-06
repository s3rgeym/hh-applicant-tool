import logging

import requests

from .base import AIError

logger = logging.getLogger(__package__)


class OpenAIError(AIError):
    pass


class OpenAIChat:
    chat_endpoint: str = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        token: str,
        model: str,
        system_prompt: str,
        proxies: dict[str, str] | None = None,
        session: requests.Session | None = None,
    ):
        self.token = token
        self.model = model
        self.system_prompt = system_prompt
        self.proxies = proxies
        self.session = session or requests.session()

    def default_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
        }

    def send_message(self, message: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": message},
            ],
            "temperature": 0.7,
            "max_completion_tokens": 1000,
        }

        try:
            response = self.session.post(
                self.chat_endpoint,
                json=payload,
                headers=self.default_headers(),
                proxies=self.proxies,
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            if "error" in data:
                raise OpenAIError(data["error"]["message"])

            assistant_message = data["choices"][0]["message"]["content"]

            return assistant_message

        except requests.exceptions.RequestException as ex:
            raise OpenAIError(str(ex)) from ex
