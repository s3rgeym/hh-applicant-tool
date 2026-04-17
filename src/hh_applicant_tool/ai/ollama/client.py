from __future__ import annotations

import base64
import logging
import time
from dataclasses import KW_ONLY, dataclass, field
from email.utils import parsedate_to_datetime
from threading import Lock
from typing import Any

from ..base import AIError

logger = logging.getLogger(__package__)


class OllamaError(AIError):
    pass


@dataclass
class ChatOllama:
    api_key: str

    _: KW_ONLY

    base_url: str
    system_prompt: str | None = None
    timeout: float = 15.0

    max_retries: int = 5

    temperature: float = 0.0
    max_tokens: int = 1000
    model: str | None = None
    think: bool | str | None = None

    rate_limit: int = 40

    session: Any = field(default_factory=lambda: __import__("requests").Session())

    _previous_request_time: float = field(default=0.0, init=False)
    _lock: Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lock = Lock()

    def _default_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
        }

    @property
    def _min_request_interval(self) -> float:
        return 60.0 / self.rate_limit if self.rate_limit > 0 else 0.0

    def _request(self, payload: dict) -> Any:
        with self._lock:
            if self._previous_request_time > 0:
                delay = (
                    self._min_request_interval
                    - time.monotonic()
                    + self._previous_request_time
                )
                if delay > 0:
                    logger.debug("Wait %.2fs before Ollama request", delay)
                    time.sleep(delay)

            try:
                return self.session.post(
                    self.base_url,
                    json=payload,
                    headers=self._default_headers(),
                    timeout=self.timeout,
                )
            except Exception as ex:
                raise OllamaError(f"Network error: {ex}") from ex
            finally:
                self._previous_request_time = time.monotonic()

    def _get_retry_delay(self, response: Any, attempt: int) -> float:
        min_interval = self._min_request_interval or 1.0
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), min_interval)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after).timestamp()
                    return max(retry_at - time.time(), min_interval)
                except (TypeError, ValueError, OverflowError):
                    pass

        return max(min_interval * (attempt + 1), 1.0)

    def complete(self, message: str) -> str:
        messages = []

        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": message})

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("AI запрос: %s", message)

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        if self.think is not None:
            payload["think"] = self.think

        for attempt in range(self.max_retries + 1):
            try:
                response = self._request(payload)
            except Exception as ex:
                raise OllamaError(f"Network error: {ex}") from ex

            if response.status_code == 429:
                if attempt >= self.max_retries:
                    raise OllamaError("Ollama rate limit exceeded")

                delay = self._get_retry_delay(response, attempt)
                logger.warning(
                    "Ollama returned 429 Too Many Requests, retry in %.2fs",
                    delay,
                )
                time.sleep(delay)
                continue

            try:
                response.raise_for_status()
            except Exception as ex:
                raise OllamaError(f"Network error: {ex}") from ex

            try:
                data = response.json()
            except ValueError as ex:
                raise OllamaError(f"Invalid JSON response: {ex}") from ex

            if "error" in data:
                raise OllamaError(data["error"]["message"])

            try:
                assistant_message = data["choices"][0]["message"]["content"]
                return assistant_message if assistant_message is not None else ""
            except (KeyError, IndexError) as ex:
                raise OllamaError(f"Invalid response format: {ex}") from ex

        raise OllamaError("Ollama request failed after retries")

    def solve_captcha(self, image_data: bytes) -> str:
        image_base64 = base64.b64encode(image_data).decode("utf-8")
        content_type = "image/png"
        messages = []

        system_prompt = (
            "Ты должен распознать текст на изображении. "
            "Верни ТОЛЬКО текст, без каких-либо объяснений или дополнительных символов."
        )

        messages.append({"role": "system", "content": system_prompt})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{content_type};base64,{image_base64}"
                        },
                    },
                    {
                        "type": "text",
                        "text": "Распознай текст на изображении. Верни только результат распознавания (текст на изображении).",
                    },
                ],
            }
        )

        logger.debug(
            "AI запрос на распознавание капчи: %d bytes", len(image_data)
        )

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 20,
            "stream": False,
        }
        if self.think is not None:
            payload["think"] = self.think

        for attempt in range(self.max_retries + 1):
            try:
                response = self._request(payload)
            except Exception as ex:
                raise OllamaError(f"Network error: {ex}") from ex

            if response.status_code == 429:
                if attempt >= self.max_retries:
                    raise OllamaError("Ollama rate limit exceeded")

                delay = self._get_retry_delay(response, attempt)
                logger.warning(
                    "Ollama returned 429 Too Many Requests, retry in %.2fs",
                    delay,
                )
                time.sleep(delay)
                continue

            try:
                response.raise_for_status()
            except Exception as ex:
                raise OllamaError(f"Network error: {ex}") from ex

            try:
                data = response.json()
            except ValueError as ex:
                raise OllamaError(f"Invalid JSON response: {ex}") from ex

            if "error" in data:
                raise OllamaError(data["error"]["message"])

            try:
                captcha_text = data["choices"][0]["message"]["content"]
                if captcha_text:
                    captcha_text = captcha_text.strip()
                logger.debug("Распознанный текст капчи: %s", captcha_text)
                return captcha_text if captcha_text else ""
            except (KeyError, IndexError) as ex:
                raise OllamaError(f"Invalid response format: {ex}") from ex

        raise OllamaError("Captcha recognition failed after retries")
