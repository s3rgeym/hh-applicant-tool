import logging
import time
from dataclasses import KW_ONLY, dataclass, field
from email.utils import parsedate_to_datetime
from threading import Lock

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
    min_request_interval: float = 1.0
    max_retries: int = 5
    temperature: float = 0.7
    max_completion_tokens: int = 1000
    model: str | None = None
    completion_endpoint: str = None
    session: requests.Session = field(default_factory=requests.Session)
    _previous_request_time: float = field(default=0.0, init=False)
    _lock: Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.completion_endpoint = (
            self.completion_endpoint or DEFAULT_COMPLETION_ENDPOINT
        )
        self._lock = Lock()

    def _default_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
        }

    def _request(self, payload: dict) -> requests.Response:
        with self._lock:
            delay = (
                self.min_request_interval
                - time.monotonic()
                + self._previous_request_time
            )
            if delay > 0:
                logger.debug("Wait %.2fs before OpenAI request", delay)
                time.sleep(delay)

            try:
                return self.session.post(
                    self.completion_endpoint,
                    json=payload,
                    headers=self._default_headers(),
                    timeout=self.timeout,
                )
            finally:
                self._previous_request_time = time.monotonic()

    def _get_retry_delay(self, response: requests.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), self.min_request_interval)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after).timestamp()
                    return max(
                        retry_at - time.time(),
                        self.min_request_interval,
                    )
                except (TypeError, ValueError, OverflowError):
                    pass

        return max(self.min_request_interval * (attempt + 1), 1.0)

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

        for attempt in range(self.max_retries + 1):
            try:
                response = self._request(payload)
            except requests.exceptions.RequestException as ex:
                raise OpenAIError(f"Network error: {ex}") from ex

            if response.status_code == 429:
                if attempt >= self.max_retries:
                    raise OpenAIError("OpenAI rate limit exceeded")

                delay = self._get_retry_delay(response, attempt)
                logger.warning(
                    "OpenAI returned 429 Too Many Requests, retry in %.2fs",
                    delay,
                )
                time.sleep(delay)
                continue

            try:
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.RequestException as ex:
                raise OpenAIError(f"Network error: {ex}") from ex
            except ValueError as ex:
                raise OpenAIError(f"Invalid JSON response: {ex}") from ex

            if "error" in data:
                raise OpenAIError(data["error"]["message"])

            assistant_message = data["choices"][0]["message"]["content"]

            return assistant_message

        raise OpenAIError("OpenAI request failed after retries")
