import logging
from dataclasses import dataclass, field
from typing import ClassVar

import requests

from .base import AIError

logger = logging.getLogger(__package__)


class OpenAIError(AIError):
    pass


@dataclass
class ChatOpenAI:
    chat_endpoint: ClassVar[str] = "https://api.openai.com/v1/chat/completions"

    token: str
    model: str
    system_prompt: str | None = None
    temperature: float = 0.7
    max_completion_tokens: int = 1000
    session: requests.Session = field(default_factory=requests.Session)

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
            "temperature": self.temperature,
            "max_completion_tokens": self.max_completion_tokens,
        }

        try:
            response = self.session.post(
                self.chat_endpoint,
                json=payload,
                headers=self.default_headers(),
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            if "error" in data:
                raise OpenAIError(data["error"]["message"])

            assistant_message = data["choices"][0]["message"]["content"]

            return assistant_message

        except requests.exceptions.RequestException as ex:
            raise OpenAIError(f"Network error: {ex}") from ex
