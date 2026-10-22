# Блять, если класс работает с OpenAI API, то он не должен знать ничего про
# API HH и ваши проблемы с капчей. Прекратите добавлять методы, которые выходят
# за его зону ответственности.
from __future__ import annotations

import base64
import logging
import time
from dataclasses import KW_ONLY, dataclass, field
from email.utils import parsedate_to_datetime
from threading import Lock

import requests
from urllib3.util import Timeout

from ..utils.helpers import get_proxies_dict
from .base import AIChat, AIClient, AIError

DEFAULT_DELAY = 0.5
DEFAULT_TIMEOUT = 90.0
DEFAULT_CONNECT_TIMEOUT = 15.0
DEFAULT_MAX_RETRIES = 5
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_COMPLETION_TOKENS = 1000

CHAT_COMPLETIONS_ENDPOINT = "/chat/completions"

DEFAULT_RECOGNIZE_PROMPT = (
    "Распознай текст на изображении. "
    "Верни только распознанный текст без пояснений."
)


logger = logging.getLogger(__name__.split(".")[0])


class OpenAIError(AIError):
    pass


@dataclass
class OpenAIClient(AIClient):
    base_url: str
    _: KW_ONLY
    api_key: str | None = None
    model: str | None = None
    # Минимальный интервал между запросами (сек)
    delay: float | None = None
    # Общий таймаут на весь запрос
    timeout: float | None = None
    # Отдельный таймаут только на установку соединения
    connect_timeout: float | None = None

    # Параметры для retry логики
    max_retries: int | None = None
    temperature: float | None = None
    max_completion_tokens: int | None = None

    chat_completions_endpoint: str | None = None

    proxy_url: str | None = None

    session: requests.Session = field(
        default_factory=requests.Session, repr=False
    )

    # Внутренние поля
    # Момент (time.monotonic()), раньше которого нельзя отправлять
    # следующий запрос
    _next_request_time: float = field(default=0.0, init=False, repr=False)
    _lock: Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lock = Lock()
        self.delay = self.delay or DEFAULT_DELAY
        self.timeout = self.timeout or DEFAULT_TIMEOUT
        self.connect_timeout = self.connect_timeout or DEFAULT_CONNECT_TIMEOUT
        self.max_retries = self.max_retries or DEFAULT_MAX_RETRIES
        self.temperature = self.temperature or DEFAULT_TEMPERATURE
        self.max_completion_tokens = (
            self.max_completion_tokens or DEFAULT_MAX_COMPLETION_TOKENS
        )
        self.chat_completions_endpoint = (
            self.chat_completions_endpoint or CHAT_COMPLETIONS_ENDPOINT
        )

    def create_chat(
        self,
        system_prompt: str,
        *,
        history: list[dict] | None = None,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_completion_tokens: int | None = None,
        delay: float | None = None,
        timeout: float | None = None,
        connect_timeout: float | None = None,
        **extra,
    ) -> "OpenAIChat":
        """Создаёт чат с фиксированными system_prompt, историей и параметрами
        генерации."""
        delay = delay or self.delay
        timeout = timeout or self.timeout
        connect_timeout = connect_timeout or self.connect_timeout

        return OpenAIChat(
            client=self,
            system_prompt=system_prompt,
            history=list(history) if history else [],
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            delay=delay,
            timeout=timeout,
            connect_timeout=connect_timeout,
            extra=extra,
        )

    def _default_headers(self, api_key: str | None = None) -> dict[str, str]:
        api_key = api_key or self.api_key
        return {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def _request(
        self,
        payload: dict,
        api_key: str | None = None,
        delay: float | None = None,
        timeout: float | None = None,
        connect_timeout: float | None = None,
    ) -> requests.Response:
        """Выполнение запроса с минимальным интервалом между запросами.

        Если с прошлого запроса прошло больше `delay` секунд,
        ожидание не выполняется.
        """
        delay = delay or self.delay
        timeout = timeout or self.timeout
        connect_timeout = connect_timeout or self.connect_timeout
        request_timeout = Timeout(connect=connect_timeout, total=timeout)
        headers = self._default_headers(api_key)
        proxies = get_proxies_dict(self.proxy_url)

        with self._lock:
            wait = self._next_request_time - time.monotonic()
            if wait > 0:
                logger.debug("Wait %.2fs before OpenAI request", wait)
                time.sleep(wait)

            try:
                return self.session.post(
                    f"{self.base_url.rstrip('/')}/{self.chat_completions_endpoint.lstrip('/')}",
                    json=payload,
                    headers=headers,
                    timeout=request_timeout,
                    proxies=proxies,
                )
            finally:
                self._next_request_time = time.monotonic() + delay

    def _postpone_requests(self, delay: float) -> None:
        """Откладывает все следующие запросы (в том числе из других потоков)
        минимум на `delay` секунд от текущего момента."""
        with self._lock:
            self._next_request_time = max(
                self._next_request_time, time.monotonic() + delay
            )

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

    def _build_messages(
        self,
        system_prompt: str,
        user_content: str | list[dict],
        history: list[dict] | None = None,
    ) -> list[dict]:
        """Сборка списка messages: system -> history -> текущее сообщение.

        Пустой системный промпт не добавляется.
        """
        messages: list[dict] = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if history:
            messages.extend(history)

        # Пользовательское сообщение всегда обязательно
        messages.append({"role": "user", "content": user_content})
        return messages

    def _post_chat(
        self,
        messages: list[dict],
        *,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_completion_tokens: int | None = None,
        delay: float | None = None,
        timeout: float | None = None,
        connect_timeout: float | None = None,
        **extra,
    ) -> str:
        """Отправка messages в /chat/completions с retry-логикой.

        Параметры, не переданные явно (None), берутся из полей класса.
        Любые дополнительные параметры (top_p, seed, response_format...)
        добавляются в payload как есть.
        """
        delay = delay or self.delay
        timeout = timeout or self.timeout
        connect_timeout = connect_timeout or self.connect_timeout
        model = model or self.model
        payload = {
            "messages": messages,
            "temperature": (
                temperature if temperature is not None else self.temperature
            ),
            "max_completion_tokens": (
                max_completion_tokens
                if max_completion_tokens is not None
                else self.max_completion_tokens
            ),
            "stream": False,
            **extra,
        }

        if model:
            payload |= {"model": model}

        for attempt in range(self.max_retries + 1):
            try:
                response = self._request(
                    payload,
                    api_key,
                    delay,
                    timeout,
                    connect_timeout,
                )
                logger.debug(
                    "OpenAI %s %s -> %d (%.2fs)",
                    response.request.method,
                    response.url,
                    response.status_code,
                    response.elapsed.total_seconds(),
                )
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
                # Само ожидание произойдёт в _request на следующей итерации
                self._postpone_requests(delay)
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

    def complete(
        self,
        system_prompt: str,
        message: str,
        *,
        history: list[dict] | None = None,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_completion_tokens: int | None = None,
        delay: float | None = None,
        timeout: float | None = None,
        connect_timeout: float | None = None,
        **extra,
    ) -> str:
        """Генерация текста через OpenAI API.

        system_prompt — обязательный первый аргумент.
        history — предыдущие сообщения диалога в формате
        [{"role": "user" | "assistant", "content": "..."}, ...].
        """
        delay = delay or self.delay
        timeout = timeout or self.timeout
        connect_timeout = connect_timeout or self.connect_timeout
        messages = self._build_messages(system_prompt, message, history)

        logger.debug(
            "AI запрос: %s",
            message,
        )

        return self._post_chat(
            messages,
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            delay=delay,
            timeout=timeout,
            connect_timeout=connect_timeout,
            **extra,
        )

    def recognize_text(
        self,
        system_prompt: str,
        data: bytes,
        *,
        mime_type: str = "image/png",
        prompt: str = DEFAULT_RECOGNIZE_PROMPT,
        history: list[dict] | None = None,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_completion_tokens: int | None = None,
        delay: float | None = None,
        timeout: float | None = None,
        connect_timeout: float | None = None,
        **extra,
    ) -> str:
        """Распознавание текста на изображении через vision-модель."""
        delay = delay or self.delay
        timeout = timeout or self.timeout
        connect_timeout = connect_timeout or self.connect_timeout
        if not data:
            raise OpenAIError("Empty image data")

        b64 = base64.b64encode(data).decode("ascii")

        messages = self._build_messages(
            system_prompt,
            [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{b64}",
                    },
                },
            ],
            history,
        )

        logger.debug("AI vision запрос: %s, %d байт", mime_type, len(data))

        return self._post_chat(
            messages,
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            delay=delay,
            timeout=timeout,
            connect_timeout=connect_timeout,
            **extra,
        )


@dataclass
class OpenAIChat(AIChat):
    """Чат поверх OpenAIClient с фиксированными system_prompt, history
    и параметрами генерации. Все параметры задаются при создании чата.

    Не заданные (None) api_key, model, temperature и max_completion_tokens
    берутся из клиента.
    """

    client: OpenAIClient
    system_prompt: str
    _: KW_ONLY
    # Базовая история диалога, которая подставляется в каждый запрос
    history: list[dict] = field(default_factory=list, repr=False)
    api_key: str | None = field(default=None, repr=False)
    model: str | None = None
    temperature: float | None = None
    max_completion_tokens: int | None = None
    delay: float | None = None
    timeout: float | None = None
    connect_timeout: float | None = None
    # Дополнительные параметры payload (top_p, seed, response_format...),
    # уходят в запрос как есть. По умолчанию ничего лишнего не отправляется:
    # например, response_format={"type": "text"} — это и так значение по
    # умолчанию в OpenAI API, передавать его бессмысленно. Нужен он только
    # для json_object / json_schema. Локальные OpenAI-совместимые модели
    # могут отвечать ошибкой на незнакомые поля, так что без нужды их
    # не добавляем.
    extra: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.delay = self.delay or DEFAULT_DELAY
        self.timeout = self.timeout or DEFAULT_TIMEOUT
        self.connect_timeout = self.connect_timeout or DEFAULT_CONNECT_TIMEOUT

    def _params(self) -> dict:
        # None-значения клиент заменит своими полями
        return {
            "api_key": self.api_key,
            "model": self.model,
            "temperature": self.temperature,
            "max_completion_tokens": self.max_completion_tokens,
            "delay": self.delay,
            "timeout": self.timeout,
            "connect_timeout": self.connect_timeout,
            **self.extra,
        }

    def complete(
        self,
        message: str,
    ) -> str:
        """Генерация текста с параметрами этого чата."""
        return self.client.complete(
            self.system_prompt,
            message,
            history=self.history,
            **self._params(),
        )

    def recognize_text(
        self,
        data: bytes,
        *,
        mime_type: str = "image/png",
        prompt: str = DEFAULT_RECOGNIZE_PROMPT,
    ) -> str:
        """Распознавание текста на изображении с параметрами этого чата."""
        return self.client.recognize_text(
            self.system_prompt,
            data,
            mime_type=mime_type,
            prompt=prompt,
            history=self.history,
            **self._params(),
        )
