import base64
import json
import logging
import os
import time
from dataclasses import KW_ONLY, dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import Lock

import requests
from urllib3.util import Timeout

from ..constants import (
    DEFAULT_OPENAI_CONNECT_TIMEOUT,
    DEFAULT_OPENAI_TIMEOUT,
)
from .base import AIError

logger = logging.getLogger(__package__)


class OpenAIError(AIError):
    pass


# Сетевые сбои, которые имеет смысл повторить: локальная модель может
# не уложиться в таймаут, соединение может оборваться. Остальное
# (битый URL, отказ SSL) повтором не лечится
_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
)


def _is_retryable(ex: Exception) -> bool:
    return isinstance(ex, _RETRYABLE_EXCEPTIONS)


# Куда складывать картинки капчи для отладки. HH_CAPTCHA_DEBUG_DIR
# переопределяет каталог, HH_CAPTCHA_DEBUG=0 отключает сохранение.
CAPTCHA_DEBUG_DIR_ENV = "HH_CAPTCHA_DEBUG_DIR"
CAPTCHA_DEBUG_DEFAULT_DIR = "/tmp/hh-captcha-debug"
# Сколько последних картинок держим, чтобы каталог не рос бесконечно
CAPTCHA_DEBUG_KEEP = 50


def _dump_captcha_debug_image(image_data: bytes) -> Path | None:
    """Сохраняет картинку капчи на диск, чтобы её можно было рассмотреть.

    Отладка: в логе видно только размер картинки и распознанный текст,
    а что именно ушло в AI — не видно. Возвращает путь к файлу или None,
    если сохранение выключено либо не удалось.
    """
    if os.environ.get("HH_CAPTCHA_DEBUG", "1").strip().lower() in (
        "0",
        "false",
        "no",
    ):
        return None

    raw_dir = (
        os.environ.get(CAPTCHA_DEBUG_DIR_ENV, "").strip()
        or CAPTCHA_DEBUG_DEFAULT_DIR
    )
    try:
        directory = Path(raw_dir)
        directory.mkdir(parents=True, exist_ok=True)
        # Метки нужны с миллисекундами: за минуту капча может попроситься
        # несколько раз, иначе файлы затрут друг друга
        stamp = time.strftime("%Y%m%d-%H%M%S") + "-%03d" % int(
            (time.time() % 1) * 1000
        )
        path = directory / f"captcha-{stamp}.png"
        path.write_bytes(image_data)

        saved = sorted(
            directory.glob("captcha-*.png"),
            key=lambda item: item.stat().st_mtime,
        )
        for stale in saved[:-CAPTCHA_DEBUG_KEEP]:
            stale.unlink(missing_ok=True)

        logger.info("Картинка капчи сохранена: %s", path)
        return path
    except OSError as ex:
        logger.warning("Не удалось сохранить картинку капчи: %s", ex)
        return None


@dataclass
class ChatOpenAI:
    api_key: str

    _: KW_ONLY

    base_url: str
    system_prompt: str | None = None
    # Общий таймаут на весь запрос
    timeout: float = DEFAULT_OPENAI_TIMEOUT
    # Отдельный таймаут только на установку соединения
    connect_timeout: float = DEFAULT_OPENAI_CONNECT_TIMEOUT

    # Параметры для retry логики
    max_retries: int = 5

    temperature: float = 0.0
    max_completion_tokens: int = 1000
    model: str | None = None

    # количество запросов в минуту (0 = отключено)
    rate_limit: int = 40

    session: requests.Session = field(default_factory=requests.Session)

    # Внутренние поля для retry логики
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

    def _request(self, payload: dict) -> requests.Response:
        """Выполнение запроса с минимальным интервалом между запросами."""
        with self._lock:
            if self._previous_request_time > 0:
                delay = (
                    self._min_request_interval
                    - time.monotonic()
                    + self._previous_request_time
                )
                if delay > 0:
                    logger.debug("Wait %.2fs before OpenAI request", delay)
                    time.sleep(delay)

            try:
                return self.session.post(
                    self.base_url,
                    json=payload,
                    headers=self._default_headers(),
                    # Ожидание ответа урезается на время, потраченное
                    # на соединение
                    timeout=Timeout(
                        connect=self.connect_timeout, total=self.timeout
                    ),
                )
            finally:
                self._previous_request_time = time.monotonic()

    def _get_retry_delay(
        self, response: requests.Response, attempt: int
    ) -> float:
        """Вычисление задержки перед повторным запросом при 429 ошибке."""
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

    def _get_network_retry_delay(self, attempt: int) -> float:
        """Задержка перед повтором после сетевого сбоя."""
        return max(self._min_request_interval * (attempt + 1), 1.0)

    def complete(self, message: str) -> str:
        """Генерация текста через OpenAI API"""
        messages = []

        # Добавляем системный промпт только если он не пустой и не None
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        # Пользовательское сообщение всегда обязательно
        messages.append({"role": "user", "content": message})

        # Логирование запроса к AI при DEBUG уровне
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("AI системный промпт: %s", self.system_prompt)
            logger.debug("AI запрос: %s", message)

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
                if attempt >= self.max_retries or not _is_retryable(ex):
                    raise OpenAIError(f"Network error: {ex}") from ex

                delay = self._get_network_retry_delay(attempt)
                logger.warning(
                    "OpenAI network error, retry in %.2fs: %s", delay, ex
                )
                time.sleep(delay)
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

    @staticmethod
    def _parse_captcha_json(raw: str) -> str:
        """Достаёт текст капчи из JSON-ответа модели.

        Терпимо выкидываем слова вокруг JSON (модель часто пишет
        «The text is {...}»). Если же JSON нет вовсе — это ошибка
        формата: молча отдавать «текст» нельзя, в него попадёт вся
        болтовня модели и hh.ru посчитает её неверным ответом.
        """
        text = (raw or "").strip()

        start = text.find("{")
        end = text.rfind("}")
        data = None
        if start != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except ValueError as ex:
                logger.warning(
                    "Ответ модели не разобрался как JSON: %r", text[:200]
                )
                raise OpenAIError(
                    f"Модель вернула не-JSON: {text[:200]}"
                ) from ex

        if not isinstance(data, dict):
            raise OpenAIError(f"Модель вернула не-JSON: {text[:200]}")

        first = data.get("first_word")
        second = data.get("second_word")

        if not isinstance(first, str) or not isinstance(second, str):
            raise OpenAIError(
                "В JSON нет полей first_word/second_word: %s" % text[:200]
            )

        first = first.strip().lower()
        second = second.strip().lower()

        if not first or not second:
            raise OpenAIError(
                "Модель не прочитала оба слова: %r" % text[:200]
            )

        return f"{first} {second}"

    # Этому методу тут не место. Мы решаем капчу hh.ru, а тут методы для OpenAI
    def solve_captcha(self, image_data: bytes) -> str:
        # Сохраняем то, что реально уходит в AI, иначе по логу
        # непонятно, что именно модель пыталась прочитать
        _dump_captcha_debug_image(image_data)

        image_base64 = base64.b64encode(image_data).decode("utf-8")

        content_type = "image/png"

        messages = []

        system_prompt = (
            "You read CAPTCHA images. What you see is text written in "
            "small dark letters on a plain light background. The text is "
            "exactly two lowercase Cyrillic words separated by a single "
            "space, and nothing else on the image. Read the letters "
            "exactly as written: the glyphs are distorted and crossed by "
            "noise lines, so look at the shape of each letter and do not "
            "guess a word you cannot see. The letters are Cyrillic, never "
            "transliterate them into Latin letters. Copy ё as ё. Answer "
            "with a JSON object only, of the form "
            '{"first_word": "...", "second_word": "..."}, with exactly '
            "these two keys, lowercase, no explanation and no other keys. "
            "If a letter is unreadable, still answer with your best "
            "reading rather than refusing."
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
                        "text": (
                            "Read the two words in this CAPTCHA image and "
                            'answer with a JSON object {"first_word": "...", '
                            '"second_word": "..."} and nothing else.'
                        ),
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
            # JSON-объект занимает заметно больше, чем голый текст,
            # 20 токенов на {"text": "..."} могло не хватить
            "max_completion_tokens": 100,
            "stream": False,
        }

        for attempt in range(self.max_retries + 1):
            try:
                response = self._request(payload)
            except requests.exceptions.RequestException as ex:
                # Таймаут локальной модели и оборванное соединение
                # повторяем, а не роняем отклик на первой вакансии
                if attempt >= self.max_retries or not _is_retryable(ex):
                    raise OpenAIError(f"Network error: {ex}") from ex

                delay = self._get_network_retry_delay(attempt)
                logger.warning(
                    "OpenAI network error, retry in %.2fs: %s", delay, ex
                )
                time.sleep(delay)
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
                raw = data["choices"][0]["message"]["content"]
                captcha_text = self._parse_captcha_json(raw).lower()
                if captcha_text:
                    logger.debug("Распознанный текст капчи: %s", captcha_text)
                return captcha_text
            except (KeyError, IndexError) as ex:
                raise OpenAIError(f"Invalid response format: {ex}") from ex

        raise OpenAIError("Captcha recognition failed after retries")
