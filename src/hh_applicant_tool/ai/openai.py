# Блять, если класс работает с OpenAI API, то он не должен знать ничего про
# API HH и ваши проблемы с капчей. Прекратите добавлять методы, которые выходят
# за его зону ответственности.
import base64
import logging
import time
from dataclasses import KW_ONLY, dataclass, field
from email.utils import parsedate_to_datetime
from threading import Lock

import requests
from urllib3.util import Timeout

from .base import AIError

DEFAULT_DELAY = 0.5
DEFAULT_TIMEOUT = 60.0
DEFAULT_CONNECT_TIMEOUT = 10.0


logger = logging.getLogger(__package__)


class OpenAIError(AIError):
    pass


@dataclass
class ChatOpenAI:
    api_key: str

    _: KW_ONLY

    base_url: str
    system_prompt: str | None = None
    # Общий таймаут на весь запрос
    timeout: float | None = None
    # Отдельный таймаут только на установку соединения
    connect_timeout: float | None = None

    # Параметры для retry логики
    max_retries: int = 3

    temperature: float = 0.0
    max_completion_tokens: int = 1000
    model: str | None = None

    # Минимальный интервал между запросами (сек). Если с прошлого запроса
    # прошло больше — не ждём.
    delay: float | None = None

    session: requests.Session = field(default_factory=requests.Session)

    # Внутренние поля
    _previous_request_time: float = field(default=0.0, init=False)
    _lock: Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lock = Lock()
        self.delay = self.delay or DEFAULT_DELAY
        self.timeout = self.timeout or DEFAULT_TIMEOUT
        self.connect_timeout = self.connect_timeout or DEFAULT_CONNECT_TIMEOUT

    def _default_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
        }

    def _request(self, payload: dict) -> requests.Response:
        """Выполнение запроса с минимальным интервалом между запросами.

        Если с прошлого запроса прошло больше `delay` секунд,
        ожидание не выполняется.
        """
        timeout = Timeout(connect=self.connect_timeout, total=self.timeout)
        headers = self._default_headers()

        with self._lock:
            if self._previous_request_time > 0:
                delay = self.delay - (
                    time.monotonic() - self._previous_request_time
                )
                if delay > 0:
                    logger.debug("Wait %.2fs before OpenAI request", delay)
                    time.sleep(delay)

            try:
                return self.session.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                )
            finally:
                self._previous_request_time = time.monotonic()

    def _get_retry_delay(
        self, response: requests.Response, attempt: int
    ) -> float:
        """Вычисление задержки перед повторным запросом при 429 ошибке."""
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 1.0)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after).timestamp()
                    return max(retry_at - time.time(), 1.0)
                except (TypeError, ValueError, OverflowError):
                    pass

        return float(attempt + 1)

    def _post_chat(self, messages: list[dict]) -> str:
        """Отправка messages в /chat/completions с retry-логикой."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_completion_tokens": self.max_completion_tokens,
            "stream": False,
        }

        for attempt in range(self.max_retries + 1):
            try:
                response = self._request(payload)
            except requests.exceptions.RequestException as ex:
                # Таймаут локальной модели и оборванное соединение
                # повторяем, а не роняем отклик на первой вакансии
                if attempt >= self.max_retries:
                    raise OpenAIError(f"Network error: {ex}") from ex

                logger.warning("OpenAI network error, retry: %s", ex)
                continue

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
                return (
                    assistant_message if assistant_message is not None else ""
                )
            except (KeyError, IndexError) as ex:
                raise OpenAIError(f"Invalid response format: {ex}") from ex

        raise OpenAIError("OpenAI request failed after retries")

    def complete(self, message: str) -> str:
        """Генерация текста через OpenAI API"""
        messages = []

        # Добавляем системный промпт только если он не пустой и не None
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        # Пользовательское сообщение всегда обязательно
        messages.append({"role": "user", "content": message})

        logger.debug("AI системный промпт: %s", self.system_prompt)
        logger.debug("AI запрос: %s", message)

        return self._post_chat(messages)

    def recognize_text(
        self,
        data: bytes,
        *,
        mime_type: str = "image/png",
        prompt: str = (
            "Распознай текст на изображении. "
            "Верни только распознанный текст без пояснений."
        ),
    ) -> str:
        """Распознавание текста на изображении через vision-модель."""
        if not data:
            raise OpenAIError("Empty image data")

        b64 = base64.b64encode(data).decode("ascii")

        messages: list[dict] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{b64}",
                        },
                    },
                ],
            }
        )

        logger.debug("AI vision запрос: %s, %d байт", mime_type, len(data))

        return self._post_chat(messages)
