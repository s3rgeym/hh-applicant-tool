import logging
import time
from dataclasses import KW_ONLY, dataclass, field
from email.utils import parsedate_to_datetime
from threading import Lock
from typing import Callable

import requests

from .base import AIError

logger = logging.getLogger(__package__)

DEFAULT_COMPLETION_ENDPOINT = "https://api.openai.com/v1/chat/completions"


class OpenAIError(AIError):
    pass


@dataclass
class ChatOpenAI:
    # Основной параметр - api_key (для совместимости также поддерживается token)
    api_key: str

    _: KW_ONLY

    token: str = None
    base_url: str = None
    system_prompt: str | None = None
    timeout: float = 15.0

    # Параметры для retry логики
    min_request_interval: float = 1.0
    max_retries: int = 5

    temperature: float = 0.7
    max_completion_tokens: int = 1000
    model: str | None = None

    # устаревший параметр, для совместимости
    completion_endpoint: str = None

    # Rate limiting: количество запросов в минуту (0 = отключено)
    rate_limit: int = 40

    session: requests.Session = field(default_factory=requests.Session)

    # Callback для логирования rate limiting
    log_callback: Callable[[str], None] = None

    # Внутренние поля для retry логики
    _previous_request_time: float = field(default=0.0, init=False)
    _lock: Lock = field(init=False, repr=False)

    # Внутренние поля для rate limiting
    _request_times: list = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.completion_endpoint = (
            self.completion_endpoint or DEFAULT_COMPLETION_ENDPOINT
        )
        self._lock = Lock()

        if self.log_callback is None:
            self.log_callback = lambda msg: logger.debug(msg)

    def _default_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
        }

    def _wait_for_rate_limit(self) -> None:
        """Ожидание для соблюдения rate limit (запросов в минуту)."""
        if self.rate_limit <= 0:
            return  # отключен

        now = time.time()

        # очищаем старые записи (старше 60 секунд)
        self._request_times = [t for t in self._request_times if now - t < 60]

        if len(self._request_times) >= self.rate_limit:
            # вычисляем время ожидания
            oldest = self._request_times[0]
            wait_time = 60 - (now - oldest) + 0.1  # +0.1 для безопасности
            if wait_time > 0:
                self.log_callback(
                    f"Rate limit reached ({self.rate_limit}/min). Waiting {wait_time:.1f}s..."
                )
                time.sleep(wait_time)
                # после ожидания очищаем старые записи
                now = time.time()
                self._request_times = [t for t in self._request_times if now - t < 60]

        self._request_times.append(time.time())

    def _request(self, payload: dict) -> requests.Response:
        """Выполнение запроса с минимальным интервалом между запросами."""
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
        """Вычисление задержки перед повторным запросом при 429 ошибке."""
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
        """Отправка сообщения в OpenAI API с retry и rate limiting."""
        # Соблюдаем rate limit
        self._wait_for_rate_limit()

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

            try:
                assistant_message = data["choices"][0]["message"]["content"]
                return assistant_message
            except (KeyError, IndexError) as ex:
                raise OpenAIError(f"Invalid response format: {ex}") from ex

        raise OpenAIError("OpenAI request failed after retries")
