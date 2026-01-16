import logging
from dataclasses import KW_ONLY, dataclass, field

import requests

from .base import AIError

logger = logging.getLogger(__package__)


DEFAULT_COMPLETION_ENDPOINT = "https://api.openai.com/v1/chat/completions"


class OpenAIError(AIError):
    pass


@dataclass
class ChatOpenAI:
    token: str
    _: KW_ONLY
    system_prompt: str | None = None
    timeout: float = 15.0
    temperature: float = 0.7
    max_completion_tokens: int = 1000
    model: str | None = None
    completion_endpoint: str = None
    session: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        self.completion_endpoint = (
            self.completion_endpoint or DEFAULT_COMPLETION_ENDPOINT
        )

    def _default_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
        }

    def send_message(self, message: str) -> str:
        messages = []

        # Добавляем системный промпт только если он не пустой и не None
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        # Пользовательское сообщение всегда обязательно
        messages.append({"role": "user", "content": message})

        payload = {
            "messages": messages,
            "temperature": self.temperature,
            "max_completion_tokens": self.max_completion_tokens,
        }

        if self.model:
            payload["model"] = self.model

        try:
            response = self.session.post(
                self.completion_endpoint,
                json=payload,
                headers=self._default_headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()

            data = response.json()
            if "error" in data:
                raise OpenAIError(data["error"]["message"])

            assistant_message = data["choices"][0]["message"]["content"]

            return assistant_message

        except requests.exceptions.RequestException as ex:
            raise OpenAIError(f"Network error: {ex}") from ex
