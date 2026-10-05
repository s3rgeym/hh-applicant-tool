import base64
import json
import logging
import os
import re
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
    DEFAULT_CAPTCHA_LANGUAGE,
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


CAPTCHA_SCRIPT_LATIN = "latin"
CAPTCHA_SCRIPT_CYRILLIC = "cyrillic"
# Браузерный путь не управляет языком картинки: скрипт задаёт hh.ru, и
# какая именно выдача придёт, заранее неизвестно. Проверять алфавит
# там нельзя, иначе настоящее кириллическое чтение отбраковывалось бы
# как чужой алфавит и сожгло бы все попытки
CAPTCHA_SCRIPT_ANY = "any"

# Какой скрипт ждём в ответе, когда попросили картинку на этом языке.
# Русская картинка всегда кириллическая, английская всегда латинская,
# поэтому сопоставление однозначное
CAPTCHA_SCRIPT_BY_LANGUAGE = {
    "en": CAPTCHA_SCRIPT_LATIN,
    "ru": CAPTCHA_SCRIPT_CYRILLIC,
}

# Буквы чужого алфавита в ответе. Раньше скрипт не проверялся вовсе,
# и модель могла вернуть русские буквы в поле, где ждут латиницу:
# такой ответ hh.ru засчитывает как промах
_LATIN_LETTER_RE = re.compile(r"[a-z]")
_CYRILLIC_LETTER_RE = re.compile(r"[Ѐ-ӿ]")


def captcha_script(language: str) -> str:
    """Ожидаемый алфавит ответа для запрошенного языка картинки."""
    key = (language or "").strip().lower()

    if key == CAPTCHA_SCRIPT_ANY:
        return CAPTCHA_SCRIPT_ANY

    return CAPTCHA_SCRIPT_BY_LANGUAGE.get(key, CAPTCHA_SCRIPT_LATIN)


def _foreign_letters(text: str, script: str) -> list[str]:
    """Буквы чужого алфавита: их в ответе быть не должно."""
    if script == CAPTCHA_SCRIPT_CYRILLIC:
        pattern = _LATIN_LETTER_RE
    elif script == CAPTCHA_SCRIPT_LATIN:
        pattern = _CYRILLIC_LETTER_RE
    else:
        return []

    return sorted(set(pattern.findall(text.lower())))


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
    max_retries: int = 3

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
    def _parse_captcha_json(
        raw: str,
        script: str = CAPTCHA_SCRIPT_LATIN,
    ) -> str:
        """Достаёт текст капчи из JSON-ответа модели.

        Терпимо выкидываем слова вокруг JSON (модель часто пишет
        «The text is {...}»). Если же JSON нет вовсе — это ошибка
        формата: молча отдавать «текст» нельзя, в него попадёт вся
        болтовня модели и hh.ru посчитает её неверным ответом.

        Проверка алфавита: модель на латинской картинке может ответить
        русскими буквами и наоборот. Раньше такой ответ уходил в поле
        ввода как есть, и hh.ru засчитывал его как промах. Теперь это
        ошибка чтения, а не ответ.
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

        captcha_text = f"{first} {second}"

        foreign = _foreign_letters(captcha_text, script)
        if foreign:
            raise OpenAIError(
                "Модель ответила чужим алфавитом, ждали %s: %s в %r"
                % (script, foreign, captcha_text[:60])
            )

        return captcha_text

    # Промпт капчи hh.ru. Общая часть собрана по живым картинкам
    # 2026-10-03: слова ложатся по дуге, из-за чего модель дорисовывает
    # обрезанные слова до знакомых ("альп" вместо "альянс").
    # Неопределённость лучше ошибочной буквы, поэтому на unsure модель
    # отвечает лучшим чтением
    CAPTCHA_PROMPT_COMMON = (
        "You read CAPTCHA images from hh.ru. A picture shows two words in "
        "small dark letters on a plain light background. The words are "
        "written along an arc, so the letters at the edges are rotated and "
        "the gap between the words is not straight. Read every letter "
        "exactly as it is drawn: the glyphs are distorted, crossed by noise "
        "lines and sometimes cut off. The words are usually nonsense; do NOT "
        "repair them into real words you happen to know, copy what you see "
        "letter by letter. "
    )

    # Правила на алфавит. Раньше здесь стояло жёсткое «the letters are
    # Cyrillic, never transliterate them into Latin letters», но язык
    # картинки задаёт не ссылка на страницу, а параметр lang у
    # POST /captcha: при lang=EN картинка приходит латинской, и это
    # указание вводило модель в заблуждение. Замер 2026-10-03 на
    # английских картинках: три чтения из трёх совпали, тогда как на
    # кириллице пять чтений из пяти тоже совпадали, но на трёх разных
    # ответах
    CAPTCHA_PROMPT_RULES = {
        CAPTCHA_SCRIPT_LATIN: (
            "The letters are LATIN lowercase; never turn them into "
            "Cyrillic letters and never transliterate them. Answer with a "
            "JSON object only, of the form "
            '{"first_word": "...", "second_word": "..."}, with exactly '
            "these two keys, lowercase Latin letters only, no punctuation, "
            "one space between the words, no explanation and no other keys. "
            "If you see three words, put the first one in first_word and the "
            "remaining two joined by a space in second_word. If a letter is "
            "unreadable, still answer with your best reading rather than "
            "refusing."
        ),
        CAPTCHA_SCRIPT_CYRILLIC: (
            "The letters are Cyrillic, never transliterate them into Latin "
            "letters. Copy ё as ё. Answer with a JSON object only, of the "
            "form "
            '{"first_word": "...", "second_word": "..."}, with exactly '
            "these two keys, lowercase, no explanation and no other keys. "
            "If you see three words, put the first one in first_word and the "
            "remaining two joined by a space in second_word. If a letter is "
            "unreadable, still answer with your best reading rather than "
            "refusing."
        ),
        CAPTCHA_SCRIPT_ANY: (
            "Keep whichever alphabet the picture uses, do not convert the "
            "letters to another script. Answer with a JSON object only, of "
            "the form "
            '{"first_word": "...", "second_word": "..."}, with exactly '
            "these two keys, lowercase, no punctuation, no explanation and "
            "no other keys. If you see three words, put the first one in "
            "first_word and the remaining two joined by a space in "
            "second_word. If a letter is unreadable, still answer with your "
            "best reading rather than refusing."
        ),
    }

    CAPTCHA_USER_PROMPT = {
        CAPTCHA_SCRIPT_LATIN: (
            "Read the two Latin words in this CAPTCHA image and answer with "
            'a JSON object {"first_word": "...", "second_word": "..."} and '
            "nothing else."
        ),
        CAPTCHA_SCRIPT_CYRILLIC: (
            "Read the two Cyrillic words in this CAPTCHA image and answer "
            'with a JSON object {"first_word": "...", "second_word": "..."} '
            "and nothing else."
        ),
        CAPTCHA_SCRIPT_ANY: (
            "Read the two words in this CAPTCHA image and answer with a "
            'JSON object {"first_word": "...", "second_word": "..."} and '
            "nothing else."
        ),
    }

    # При нулевой температуре все выборки совпадают и голосование
    # превращается в один и тот же запрос
    CAPTCHA_SAMPLE_TEMPERATURE = 0.7

    @staticmethod
    def _captcha_vote_key(text: str) -> str:
        # ё и е в капче неразличимы, для подсчёта голосов это один ответ
        return text.replace("ё", "е")

    def _captcha_payload(
        self,
        image_base64: str,
        content_type: str,
        temperature: float,
        script: str,
    ) -> dict:
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        self.CAPTCHA_PROMPT_COMMON
                        + self.CAPTCHA_PROMPT_RULES[script]
                    ),
                },
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
                            "text": self.CAPTCHA_USER_PROMPT[script],
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
        script: str = CAPTCHA_SCRIPT_LATIN,
        throttle: bool = True,
    ) -> str:
        image_base64 = base64.b64encode(image_data).decode("utf-8")

        content_type = "image/png"

        payload = self._captcha_payload(
            image_base64, content_type, temperature, script
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
                captcha_text = self._parse_captcha_json(
                    raw, script
                ).lower()
                if captcha_text:
                    logger.debug("Распознанный текст капчи: %s", captcha_text)
                return captcha_text
            except (KeyError, IndexError) as ex:
                raise OpenAIError(f"Invalid response format: {ex}") from ex

        raise OpenAIError("Captcha recognition failed after retries")

    def solve_captcha(
        self,
        image_data: bytes,
        language: str = DEFAULT_CAPTCHA_LANGUAGE,
    ) -> str:
        """Одно чтение картинки. Дёшево, но ошибается примерно в половине
        случаев, поэтому для боевого прогона лучше голосование."""
        # Сохраняем то, что реально уходит в AI, иначе по логу
        # непонятно, что именно модель пыталась прочитать
        _dump_captcha_debug_image(image_data)

        return self._read_captcha_once(
            image_data, self.temperature, script=captcha_script(language)
        )

    def solve_captcha_consensus(
        self,
        image_data: bytes,
        *,
        samples: int = 5,
        min_votes: int = 3,
        language: str = DEFAULT_CAPTCHA_LANGUAGE,
    ) -> str | None:
        """Несколько независимых чтений, ответ отдаётся только при согласии.

        None означает «модель не уверена». Такой ответ отправлять нельзя:
        hh.ru записывает неверный ответ как isBot, и один промах вредит
        больше, чем пропущенная вакансия.

        Осторожно, это порог устойчивости, а не проверка правоты. Замер
        2026-10-03 на кириллице: пять чтений различались на одну букву,
        но когда все пять совпадали, ответ всё равно оказывался
        неверным — просто модель была в этом уверена. С разными
        моделями голосование работает как надо, с одной моделью оно
        отсекает только нестабильные чтения. На латинских картинках
        согласие заметно выше, но правильность от этого не
        гарантирована.
        """
        _dump_captcha_debug_image(image_data)
        script = captcha_script(language)
        started = time.monotonic()

        with ThreadPoolExecutor(max_workers=samples) as pool:
            futures = [
                pool.submit(
                    self._read_captcha_once,
                    image_data,
                    self.CAPTCHA_SAMPLE_TEMPERATURE,
                    script=script,
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
        # Замер 2026-10-03: пять параллельных чтений латинской картинки
        # собираются примерно за 13 с, поэтому время в лог стоит
        logger.info(
            "Чтений капчи: %s, порог согласия %s, собрано за %.1f с: %s",
            len(readings),
            min_votes,
            time.monotonic() - started,
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
