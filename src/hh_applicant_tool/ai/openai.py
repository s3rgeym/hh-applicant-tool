import base64
import json
import logging
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import KW_ONLY, dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import Lock, local

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
    # Сессия на каждый поток: requests.Session не потокобезопасен, а
    # голосование по капче шлёт несколько запросов одновременно
    _tls: local = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lock = Lock()
        self._tls = local()

    def _thread_session(self) -> requests.Session:
        session = getattr(self._tls, "session", None)
        if session is None:
            session = requests.Session()
            self._tls.session = session
        return session

    def _default_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
        }

    @property
    def _min_request_interval(self) -> float:
        return 60.0 / self.rate_limit if self.rate_limit > 0 else 0.0

    def _request(
        self, payload: dict, *, throttle: bool = True
    ) -> requests.Response:
        """Выполнение запроса с минимальным интервалом между запросами.

        throttle=False снимает и интервал, и блокировку: этим пользуется
        голосование по капче, где несколько одинаковых запросов идут
        одновременно и ждать их по очереди бессмысленно.
        """
        if not throttle:
            return self._thread_session().post(
                self.base_url,
                json=payload,
                headers=self._default_headers(),
                timeout=Timeout(
                    connect=self.connect_timeout, total=self.timeout
                ),
            )

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

    # Промпт капчи hh.ru. Собран по живым картинкам 2026-10-03: слова
    # ложатся по дуге, из-за чего модель дорисовывает обрезанные слова
    # до знакомых ("альп" вместо "альянс"). Неопределённость лучше
    # ошибочной буквы, поэтому на unsure модель отвечает лучшим чтением
    CAPTCHA_SYSTEM_PROMPT = (
        "You read CAPTCHA images from hh.ru. A picture shows two Russian "
        "words in small dark letters on a plain light background. The words "
        "are written along an arc, so the letters at the edges are rotated "
        "and the gap between the words is not straight. Read every letter "
        "exactly as it is drawn: the glyphs are distorted, crossed by noise "
        "lines and sometimes cut off. The words are usually nonsense; do NOT "
        "repair them into real Russian words you happen to know, copy what "
        "you see letter by letter. The letters are Cyrillic, never "
        "transliterate them into Latin letters. Copy ё as ё. Answer with a "
        "JSON object only, of the form "
        '{"first_word": "...", "second_word": "..."}, with exactly these '
        "two keys, lowercase, no explanation and no other keys. If you see "
        "three words, put the first one in first_word and the remaining two "
        "joined by a space in second_word. If a letter is unreadable, still "
        "answer with your best reading rather than refusing."
    )

    CAPTCHA_USER_PROMPT = (
        "Read the two words in this CAPTCHA image and answer with a JSON "
        'object {"first_word": "...", "second_word": "..."} and nothing '
        "else."
    )

    # При нулевой температуре все выборки совпадают и голосование
    # превращается в один и тот же запрос
    CAPTCHA_SAMPLE_TEMPERATURE = 0.7

    @staticmethod
    def _captcha_vote_key(text: str) -> str:
        # ё и е в капче неразличимы, для подсчёта голосов это один ответ
        return text.replace("ё", "е")

    def _captcha_payload(
        self, image_base64: str, content_type: str, temperature: float
    ) -> dict:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.CAPTCHA_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": (
                                    f"data:{content_type};base64,"
                                    f"{image_base64}"
                                ),
                                # мелкие буквы по дуге в режиме по
                                # умолчанию читаются заметно хуже
                                "detail": "high",
                            },
                        },
                        {
                            "type": "text",
                            "text": self.CAPTCHA_USER_PROMPT,
                        },
                    ],
                },
            ],
            "temperature": temperature,
            # JSON-объект занимает заметно больше, чем голый текст,
            # 20 токенов на {"text": "..."} могло не хватить
            "max_completion_tokens": 100,
            "stream": False,
        }

    # Этому методу тут не место. Мы решаем капчу hh.ru, а тут методы для OpenAI
    def _read_captcha_once(
        self,
        image_data: bytes,
        temperature: float,
        *,
        throttle: bool = True,
    ) -> str:
        image_base64 = base64.b64encode(image_data).decode("utf-8")

        content_type = "image/png"

        payload = self._captcha_payload(
            image_base64, content_type, temperature
        )

        logger.debug(
            "AI запрос на распознавание капчи: %d bytes, выборка на "
            "температуре %.2f",
            len(image_data),
            temperature,
        )

        for attempt in range(self.max_retries + 1):
            try:
                response = self._request(payload, throttle=throttle)
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

    def solve_captcha(self, image_data: bytes) -> str:
        """Одно чтение картинки. Дёшево, но ошибается примерно в половине
        случаев, поэтому для боевого прогона лучше голосование."""
        # Сохраняем то, что реально уходит в AI, иначе по логу
        # непонятно, что именно модель пыталась прочитать
        _dump_captcha_debug_image(image_data)

        return self._read_captcha_once(image_data, self.temperature)

    def solve_captcha_consensus(
        self,
        image_data: bytes,
        *,
        samples: int = 5,
        min_votes: int = 3,
    ) -> str | None:
        """Несколько независимых чтений, ответ отдаётся только при согласии.

        None означает «модель не уверена». Такой ответ отправлять нельзя:
        hh.ru записывает неверный ответ как isBot, и один промах вредит
        больше, чем пропущенная вакансия.

        Осторожно, это порог устойчивости, а не проверка правоты. Замер
        2026-10-03: пять чтений различались на одну букву, но когда все
        пять совпадали, ответ всё равно оказывался неверным — просто
        модель была в этом уверена. С разными моделями голосование
        работает как надо, с одной моделью оно отсекает только
        нестабильные чтения.
        """
        _dump_captcha_debug_image(image_data)

        with ThreadPoolExecutor(max_workers=samples) as pool:
            futures = [
                pool.submit(
                    self._read_captcha_once,
                    image_data,
                    self.CAPTCHA_SAMPLE_TEMPERATURE,
                    throttle=False,
                )
                for _ in range(samples)
            ]
            readings: list[str] = []
            for future in futures:
                try:
                    readings.append(future.result())
                except Exception as ex:
                    logger.debug(
                        "Одно из чтений капчи не удалось (%s): %s",
                        type(ex).__name__,
                        str(ex)[:200],
                    )

        if not readings:
            raise OpenAIError("Captcha recognition failed after retries")

        votes = Counter(self._captcha_vote_key(r) for r in readings)
        best_key, top = votes.most_common(1)[0]
        logger.info(
            "Чтений капчи: %s, порог согласия %s, собрано за %s: %s",
            len(readings),
            min_votes,
            best_key,
            [self._captcha_vote_key(r) for r in readings],
        )
        if top < min_votes:
            return None

        # Отдаём то написание, которое модель выдала чаще, а не
        # нормализованный ключ: в капче встречается и ё
        spellings = Counter(
            r for r in readings if self._captcha_vote_key(r) == best_key
        )
        return spellings.most_common(1)[0][0]
