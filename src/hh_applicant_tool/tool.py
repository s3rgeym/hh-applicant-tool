from __future__ import annotations

import argparse
import base64
import copy
import html
import json
import logging
import random
import signal
import smtplib
import sys
import time
import types
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import KW_ONLY, dataclass
from functools import cached_property
from http.cookiejar import MozillaCookieJar
from importlib import import_module
from itertools import count
from json.decoder import JSONDecodeError
from os import getenv
from pathlib import Path
from pkgutil import iter_modules
from typing import (
    Any,
    Callable,
    Iterable,
    Literal,
    NamedTuple,
    NotRequired,
    TypedDict,
)
from urllib.parse import parse_qs, quote, urljoin, urlsplit
from weakref import WeakValueDictionary

import requests

from hh_applicant_tool.utils.package import PACKAGE_NAME, get_package_version

from . import ai, api
from .constants import (
    ACCEPT_HEADER,
    ACCEPT_LANGUAGE_HEADER,
    ANDROID_CLIENT_ID,
    ANDROID_CLIENT_SECRET,
    ANDROID_WEBVIEW_USERAGENT,
    CAPTCHA_PROMPT,
    CAPTCHA_SOLVE_MAX_DELAY,
    CAPTCHA_SOLVE_MIN_DELAY,
    CAPTCHA_SUCCESS_BACKURL,
    CONFIG_DIR,
    CONFIG_FILENAME,
    COOKIES_FILENAME,
    DEFAULT_CAPTCHA_LANGUAGE,
    DEFAULT_DESKTOP_USERAGENT,
    GITHUB_REPO_URL,
    HH_BASE_URL,
    HH_DOMAIN_RE,
    LOG_FILENAME,
    MAX_CAPTCHA_ATTEMPTS,
    TELEGRAM_CHAT_URL,
    TOKEN_CONFIG_FILENAME,
)
from .errors import (
    CaptchaError,
    Error,
    OperationCanceled,
    OperationError,
)
from .utils.argparse import ArgumentFormatter
from .utils.config import ConfigJSON, ConfigTOML
from .utils.datatypes import ResumePlaceholders
from .utils.helpers import get_proxies_dict
from .utils.log import setup_logger
from .utils.string import shorten
from .utils.system import has_gui_support, is_docker
from .utils.term import print_kitty_image, print_sixel_image, setup_terminal
from .utils.user_agent import generate_android_useragent

_ACCEPT_IMAGE_HEADERS = types.MappingProxyType(
    {
        "Accept": "image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5"
    }
)

_CAPTCHA_HEADERS = types.MappingProxyType(
    {
        "X-Hhtmfrom": "",
        "X-Hhtmsource": "account_captcha",
    }
)

OPERATIONS = "operations"

try:
    import tkinter as tk
    from tkinter import ttk

    TKINTER_IMPORTED = True
except ImportError:
    TKINTER_IMPORTED = False


logger = logging.getLogger(__name__.split(".")[0])


class XHRResult(TypedDict):
    http_status: int
    http_headers: dict[str, str]
    text: NotRequired[str]
    success: NotRequired[bool]
    hhcaptcha: NotRequired[dict[str, str]]
    ...


class HHLuxInitialState(TypedDict):
    redirectConfig: dict[str, Any]
    ...


class CaptchaImage(NamedTuple):
    data: bytes
    key: str


class CaptchaSolution(NamedTuple):
    key: str
    state: str
    text: str


class BaseOperation:
    def setup_parser(self, parser: argparse.ArgumentParser) -> None: ...

    def run(
        self,
        tool: HHApplicantTool,
        args: BaseNamespace,  # pyright: ignore[reportUnusedParameter]
    ) -> None | int:
        raise NotImplementedError()


class BaseNamespace(argparse.Namespace):
    verbosity: int
    use_ai: bool
    operation_run: Callable[[HHApplicantTool, BaseNamespace], None | int] | None
    # argument_default=SUPPRESS: поля нет, пока флаг не передан
    config_dir: Path
    profile_id: str
    api_delay: float
    base_url: str
    user_agent: str
    proxy_url: str
    openai_proxy_url: str
    openai_delay: str
    openai_timeout: float
    openai_connect_timeout: float
    use_kitty: bool
    use_sixel: bool
    captcha_lang: Literal["RU", "EN"]
    captcha_handling: bool


@dataclass
class HHApplicantTool:
    _: KW_ONLY
    api_delay: float | None = None
    base_url: str | None = None
    captcha_manual: bool = False
    captcha_handling: bool = True
    captcha_lang: str | None = None
    config_dir: Path | None = None
    openai_connect_timeout: float | None = None
    openai_delay: float | None = None
    openai_proxy_url: str | None = None
    openai_timeout: float | None = None
    profile_id: str | None = None
    proxy_url: str | None = None
    use_ai: bool = False
    use_kitty: bool = False
    use_sixel: bool = False
    user_agent: str | None = None
    verbosity: int = 0

    @classmethod
    def _create_parser(cls) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description=cls.__doc__,
            formatter_class=ArgumentFormatter,
            argument_default=argparse.SUPPRESS,
        )
        # TODO: можно переписать описания
        parser.add_argument(
            "-v",
            "--verbosity",
            help="При использовании от одного и более раз увеличивает количество отладочной информации в выводе",  # noqa: E501
            action="count",
            default=0,
        )
        parser.add_argument(
            "-c",
            "--config-dir",
            "--config",
            help="Путь до директории с конфигом",
            type=Path,
        )
        parser.add_argument(
            "--profile-id",
            "--profile",
            help="Используемый профиль — подкаталог в --config-dir. Так же можно передать через переменную окружения HH_PROFILE_ID.",
        )
        parser.add_argument(
            "-d",
            "--api-delay",
            "--delay",
            type=float,
            help="Задержка между запросами к API HH по умолчанию",
        )
        parser.add_argument(
            "--base-url",
            help="Базовый URL сайта чтобы избежать лишних редиректов.",
        )
        parser.add_argument(
            "--user-agent",
            help="User-Agent для запросов к HH. Нужно притворяться каким-нибудь популярным браузером, иначе будет показывать 403 или 404 ошибку на каждый запрос",
        )
        parser.add_argument(
            "--proxy-url",
            help="Прокси, используемый для запросов и авторизации",
        )
        parser.add_argument(
            "--openai-proxy",
            "--ai-proxy",
            dest="openai_proxy_url",
            help="Отдельный прокси, используемый только для OpenAI чата",
        )
        parser.add_argument(
            "--openai-delay",
            "--ai-delay",
            help="Задержка между запросами в секундах к OpenAI по умолчанию",
        )
        parser.add_argument(
            "--openai-timeout",
            "--ai-timeout",
            type=float,
            help="Таймаут запроса к OpenAI в секундах: соединение и чтение ответа по умолчаниюю",
        )
        parser.add_argument(
            "--openai-connect-timeout",
            "--openai-connect",
            "--ai-connect-timeout",
            "--ai-connect",
            type=float,
            help="Таймаут соединения с OpenAI в секундах по умолчанию",
        )
        parser.add_argument(
            "--use-ai",
            "--ai",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Использовать AI для всех действий в т.ч. решения капчи",
        )
        parser.add_argument(
            "-k",
            "--use-kitty",
            "--kitty",
            action="store_true",
            help="Вывод капчи в kitty",
        )
        parser.add_argument(
            "-s",
            "--use-sixel",
            "--sixel",
            action="store_true",
            help="Вывод капчи в sixel",
        )
        parser.add_argument(
            "--captcha-lang",
            choices=["RU", "EN", "ru", "en"],
            help="Язык капчи. Некоторые модели распознают лучше текст на английском",
        )
        parser.add_argument(
            "--handle-captcha",
            dest="captcha_handling",
            help="Перехватывать ошибки капчи",
            action=argparse.BooleanOptionalAction,
            default=True,
        )
        parser.add_argument(
            "--manual-captcha",
            "--manual",
            dest="captcha_manual",
            help="Ручной ввод капчи. Полезен, если модель не поддерживает vision",
            action="store_true",
            default=False,
        )
        subparsers = parser.add_subparsers(help="commands")
        package_dir = Path(__file__).resolve().parent / OPERATIONS
        for _, mod_name, _ in iter_modules([str(package_dir)]):
            if mod_name.startswith("_"):
                continue
            mod = import_module(f"{__package__}.{OPERATIONS}.{mod_name}")
            op: BaseOperation = mod.Operation()
            # Кебаб Нурмагомедов
            kebab = mod_name.replace("_", "-")
            op_parser = subparsers.add_parser(
                kebab,
                aliases=getattr(op, "__aliases__", []),
                description=op.__doc__,
                formatter_class=ArgumentFormatter,
            )
            op_parser.set_defaults(operation_run=op.run)
            op.setup_parser(op_parser)
        parser.set_defaults(operation_run=None)
        return parser

    def __post_init__(self) -> None:
        self._parser = self._create_parser()

        config = self.general_config

        # Эти значения, если они не установлены, берутся из конфига и могут быть
        # изменены флагами
        self.user_agent = self.user_agent or config.get(
            "user_agent", DEFAULT_DESKTOP_USERAGENT
        )
        self.base_url = self.base_url or config.get("base_url", HH_BASE_URL)
        self.captcha_lang = self.captcha_lang or config.get(
            "captcha_lang", DEFAULT_CAPTCHA_LANGUAGE
        )

    @property
    def general_config(self) -> dict[str, Any]:
        self.config.setdefault("general", {})
        return self.config["general"]

    def _create_session(
        self,
        label: str,
        *,
        user_agent: str | None = None,
        proxies: dict[str, str] | None = None,
    ) -> requests.Session:
        session = requests.Session()
        if proxies is None:
            proxies = get_proxies_dict(self.proxy_url)

        if proxies:
            logger.debug("%s session proxies: %r", label, proxies)
            session.proxies = proxies

        # В заголовки не лезь, если не понимаешь зачем они
        session.headers.update(
            {
                "User-Agent": user_agent or self.user_agent,
                "Accept": ACCEPT_HEADER,
                "Accept-Language": ACCEPT_LANGUAGE_HEADER,
            }
        )

        logger.debug("%s session headers: %r", label, session.headers)

        return session

    @cached_property
    def session(self) -> requests.Session:
        session = self._create_session("Desktop")

        if self.cookies_file.exists():
            jar = MozillaCookieJar(str(self.cookies_file))
            jar.load(ignore_discard=True, ignore_expires=True)
            session.cookies.update(jar)

        # Запоминаем куки, которые были при инициализации
        self._cookies_fingerprint = self._get_cookie_fingerprint(
            self._get_hh_cookies(session.cookies)
        )
        return session

    @property
    def ai_configured(self) -> bool:
        return bool(self.config.get("openai"))

    @property
    def ai_enabled(self) -> bool:
        # Использование AI по умолчанию включено
        return self.use_ai and self.ai_configured

    @cached_property
    def ai_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": f"Mozilla/5.0 (compatible; {PACKAGE_NAME}/{get_package_version()}; +{GITHUB_REPO_URL})",
            }
        )
        logger.debug("AI Default Headers: %r", session.headers)
        return session

    @cached_property
    def config_dir_path(self) -> Path:
        return (
            (self.config_dir or Path(getenv("CONFIG_DIR", CONFIG_DIR)))
            / (self.profile_id or getenv("HH_PROFILE_ID", "."))
        ).resolve()

    @cached_property
    def config(self) -> ConfigTOML:
        return ConfigTOML(self.config_dir_path / CONFIG_FILENAME)

    @cached_property
    def token_config(self) -> ConfigJSON:
        return ConfigJSON(self.config_dir_path / TOKEN_CONFIG_FILENAME)

    @cached_property
    def log_file(self) -> Path:
        return self.config_dir_path / LOG_FILENAME

    @cached_property
    def cookies_file(self) -> Path:
        return self.config_dir_path / COOKIES_FILENAME

    @cached_property
    def api_client(self) -> api.client.ApiClient:
        token = self.token_config.get("token") or {}
        client_config = dict(self.config.get("api_client") or {})
        client_config.setdefault("proxy_url", self.proxy_url)
        if self.api_delay:
            client_config["delay"] = self.api_delay

        client = api.client.ApiClient(
            access_token=token.get("access_token"),
            refresh_token=token.get("refresh_token"),
            access_expires_at=token.get("access_expires_at"),
            client_id=ANDROID_CLIENT_ID,
            client_secret=ANDROID_CLIENT_SECRET,
            user_agent=generate_android_useragent(),
            captcha_handler=self.handle_captcha
            if self.captcha_handling
            else None,
            max_captcha_attempts=MAX_CAPTCHA_ATTEMPTS,
            on_token_change=self._save_token,
            **client_config,
        )

        return client

    @cached_property
    def _ai_clients(self) -> WeakValueDictionary[str, ai.OpenAIClient]:
        return WeakValueDictionary()

    def _get_ai_client(self, base_url: str) -> ai.OpenAIClient:
        """Возвращает общий AI-клиент для указанного base_url."""
        key = base_url.rstrip("/")
        client = self._ai_clients.get(key)

        if client is None:
            client = ai.OpenAIClient(base_url)
            logger.debug("client created: %r", client)
            self._ai_clients[key] = client

        return client

    def ai_chat_for(
        self,
        section: str | None = None,
        **defaults: Any,
    ) -> ai.OpenAIChat:
        """Создаёт AI-чат с настройками секции openai.<section>.

        Клиент общий для всех чатов с одинаковым base_url. В клиент
        передаётся только base_url, остальные настройки передаются чату.
        Значения из конфига перекрывают defaults.
        """
        settings = {**defaults, **self.get_openai_config(section)}
        base_url = settings.pop("base_url")
        system_prompt = settings.pop("system_prompt")
        client = self._get_ai_client(base_url)
        return client.create_chat(system_prompt, **settings)

    def get_openai_config(self, section: str | None = None) -> dict:
        """Возвращает копию конфига openai с учетом наследования от главной"""
        base_section = "openai"
        default_section = "default"
        if section is None:
            section = default_section
        elif "." in section:
            base, section = section.split(".", 1)
            if base != base_section:
                raise ValueError(
                    f"Base section must be {base_section!r}: got: {base!r}"
                )

        # Поздние секции перекрывают ранние, результат — глубокая копия
        c = self.config.get_merged(
            f"{base_section}.{default_section}",
            f"{base_section}.{section}",
        )

        if "base_url" not in c:
            where = f"[{base_section}.{section}]"
            if section != default_section:
                where += f" или [{base_section}.{default_section}]"
            raise ValueError(f"Значение 'base_url' не задано в {where}")

        if self.openai_delay:
            c.setdefault("delay", self.openai_delay)
        if self.openai_timeout:
            c.setdefault("timeout", self.openai_timeout)
        if self.openai_connect_timeout:
            c.setdefault("connect_timeout", self.openai_connect_timeout)

        return c

    def get_me(self) -> api.datatypes.User:
        return self.api_client.get("/me")

    def get_resumes(self) -> list[api.datatypes.Resume]:
        return self.api_client.get("/resumes/mine").get("items", [])

    def first_resume_id(self) -> str:
        resume = self.get_resumes()[0]
        return resume["id"]

    def get_blacklisted(self) -> list[str]:
        rv = []
        for page in count():
            r: api.datatypes.PaginatedItems[api.datatypes.EmployerShort] = (
                self.api_client.get("/employers/blacklisted", page=page)
            )
            rv += [item["id"] for item in r["items"]]
            if page + 1 >= r["pages"]:
                break
        return rv

    def get_negotiations(
        self, status: str = "active"
    ) -> Iterable[api.datatypes.Negotiation]:
        for page in count():
            r: dict[str, Any] = self.api_client.get(
                "/negotiations",
                page=page,
                per_page=100,
                status=status,
            )

            items = r.get("items", [])

            if not items:
                break

            yield from items

            if page + 1 >= r.get("pages", 0):
                break

    def parse_initial_state(
        self,
        response: requests.Response,
    ) -> HHLuxInitialState:
        """Возвращает декодированное содержимое <template id="HH-Lux-InitialState"></template>"""
        if response.status_code != 200:
            raise Error(
                f"Неожиданный код ответа: {response.status_code} {response.url}"
            )

        template_start_tag = 'id="HH-Lux-InitialState">'
        template_end_tag = "</template>"

        start_pos = response.text.find(template_start_tag)
        if (
            start_pos == -1
            or (
                end_pos := response.text.find(
                    template_end_tag, start_pos + len(template_start_tag)
                )
            )
            == -1
        ):
            raise ValueError(
                f"Теги {template_start_tag!r} и {template_end_tag!r} "
                f"не найдены на странице {response.url}"
            )

        raw_data = response.text[start_pos + len(template_start_tag) : end_pos]

        # Теперь кавычки всегда превращаются в сущности?
        if raw_data.startswith("{&#34;"):
            raw_data = html.unescape(raw_data)

        data = json.loads(raw_data)
        assert type(data) is dict
        assert "redirectConfig" in data

        return data

    def get_initial_state(self, url: str) -> HHLuxInitialState:
        r = self.session.get(url)
        logger.debug("check initial state: %s %d", r.url, r.status_code)
        return self.parse_initial_state(r)

    @staticmethod
    def _get_cookie_fingerprint(cookies) -> frozenset:
        return frozenset(
            (c.domain, c.path, c.name, c.value, c.expires, c.secure)
            for c in cookies
        )

    def _get_hh_cookies(self, cookies) -> list:
        return [
            c for c in cookies if not c.domain or HH_DOMAIN_RE.search(c.domain)
        ]

    def save_cookies(self) -> None:
        """Сохраняет cookies сессии hh в файл."""
        if "session" not in self.__dict__:
            logger.debug("Session not created, no cookies to save")
            return

        cookies = self._get_hh_cookies(self.session.cookies)
        fingerprint = self._get_cookie_fingerprint(cookies)
        if fingerprint == self._cookies_fingerprint:
            logger.debug("Cookies not changed")
            return

        jar = MozillaCookieJar(str(self.cookies_file))
        for c in cookies:
            jar.set_cookie(copy.copy(c))

        jar.save(ignore_discard=True, ignore_expires=True)
        self._cookies_fingerprint = fingerprint
        logger.info("Cookies saved to %s", self.cookies_file)

    @property
    def is_logged_in(self) -> bool:
        """Проверяет авторизован ли пользователь через сайт."""
        return self.session.get(f"{self.base_url}/settings").status_code == 200

    @property
    def xsrf_token(self) -> str | None:
        return self.session.cookies.get("_xsrf")

    @cached_property
    def smtp(self) -> smtplib.SMTP | smtplib.SMTP_SSL:
        conf = self.general_config.get("smtp", {})
        host = conf.get("host")
        port = conf.get("port")
        user = conf.get("user")
        password = conf.get("password")
        use_ssl = conf.get("ssl", False)

        if not host or not port:
            raise ValueError("SMTP host or port not configured")

        client_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
        server = client_cls(host, port)

        if not use_ssl and conf.get("starttls", True):
            server.starttls()

        if user and password:
            server.login(user, password)

        return server

    def _solve_captcha(self, image_data: bytes) -> str:
        if self.ai_enabled and not self.captcha_manual:
            logger.debug("Try recognize CAPTCHA text via AI")
            return self.captcha_ai.recognize_text(image_data)

        if self._can_use_tkinter():
            return self.prompt_captcha_tkinter(image_data)

        return self._prompt_captcha_in_terminal(image_data)

    def _can_use_tkinter(self) -> bool:
        return (
            TKINTER_IMPORTED
            and not (self.use_kitty or self.use_sixel)
            and has_gui_support()
        )

    def _prompt_captcha_in_terminal(self, image_data: bytes) -> str:
        show_image = print_kitty_image if self.use_kitty else print_sixel_image
        show_image(image_data)
        return input(CAPTCHA_PROMPT).strip()

    def solve_captcha(
        self,
        captcha_state: str,
        *,
        lang: str | None = None,
        referer_url: str | None = None,
        xsrf_token: str | None = None,
        session: requests.Session | None = None,
    ) -> CaptchaSolution:
        """Если API сайта возвращает ответ с hhcaptcha.captchaState, то
        появляется всплывающее окно для ввода капчи"""
        captcha_img = self.get_captcha_image(
            lang=lang,
            referer_url=referer_url,
            xsrf_token=xsrf_token,
            session=session,
        )
        text = self._solve_captcha(image_data=captcha_img.data)
        logger.debug(f"Текст с капчи: {text}")

        return CaptchaSolution(
            text=text,
            state=captcha_state,
            key=captcha_img.key,
        )

    @cached_property
    def webview_session(self) -> requests.Session:
        return self._create_session(
            "Android WebView", user_agent=ANDROID_WEBVIEW_USERAGENT
        )

    def handle_captcha(
        self,
        captcha_url: str,
        *,
        lang: str | None = None,
        referer_url: str | None = None,
    ) -> bool:
        """Проходит отдельную страницу с капчей (замена solve_captcha_url).

        Страница капчи обычно открывается в webview, где своя сессия, а
        не self.session. Поэтому без параметра session создаётся чистая
        сессия, и все запросы идут через неё. Чтобы потом забрать её куки,
        создайте сессию снаружи и передайте сюда.

        1. К ссылке добавляется backurl, страница открывается. Сайт может
           перекинуть на другой поддомен, итоговый URL страницы идёт в
           Referer всех следующих запросов.
        2. Получаем captcha key и картинку, решаем (solve_captcha).
        3. Отправляем text, key, state, backurl, failurl.
           302 - успех, 403 и всё остальное - ошибка.

        Возвращает True, если капча принята. Одна попытка; повтор при
        неверном вводе - на стороне вызывающего.
        """
        logger.debug("captcha url: %s", captcha_url)

        # На Андроиде WebView сохраняет куки между вызовами, поэтому будем
        # симулировать это поведение
        session = self.webview_session

        r = session.get(
            captcha_url,
            {"backurl": CAPTCHA_SUCCESS_BACKURL},
            headers={"Referer": referer_url} if referer_url else {},
        )
        r.raise_for_status()

        redirect_url = r.url
        logger.debug("Страница капчи, пойдёт в referer: %s", redirect_url)

        query = parse_qs(urlsplit(redirect_url).query)

        if "state" not in query:
            raise ValueError(f"В ссылке на капчу нет state: {redirect_url}")
        state = query["state"][0]

        assert CAPTCHA_SUCCESS_BACKURL in query.get("backurl", [])

        # Страница выставила куки в чистую сессию, токен берём из них,
        # а если куки нет - из initial state страницы
        xsrf_token = session.cookies.get("_xsrf")

        if not xsrf_token:
            raise ValueError("xsrf token отсутствует в Cookies!")

        with self.captcha_retry_delay():
            solution = self.solve_captcha(
                captcha_state=state,
                lang=lang,
                referer_url=redirect_url,
                xsrf_token=xsrf_token,
                session=session,
            )

        return self._send_captcha(
            text=solution.text,
            key=solution.key,
            state=solution.state,
            referer_url=redirect_url,
            xsrf_token=xsrf_token,
            backurl=CAPTCHA_SUCCESS_BACKURL,
            session=session,
        )

    # --- Сборка запроса -----------------------------------------------------
    @staticmethod
    def _build_xhr_headers(
        origin: str,
        xsrf: str,
        referer_url: str,
        extra_headers: dict,
    ) -> dict:
        """Стандартные XHR-заголовки; `extra_headers` перекрывает стандартные.

        Все значения уже определены и не None -- проверки делает вызывающий код.
        """
        default_headers = {
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-XSRFToken": xsrf,
            "Origin": origin,
            "Referer": referer_url,
        }

        return {
            **default_headers,
            **extra_headers,
        }

    @staticmethod
    def _parse_xhr_response(r: requests.Response) -> XHRResult:
        """Разбирает ответ в словарь и проверяет, не требует ли сервер капчу.

        - не JSON      -> {"text": ..., "http_status": ...}
        - JSON не dict -> {"data": ..., "http_status": ...}
        - в остальных случаях к словарю ответа добавляется "http_status".

        Бросает CaptchaError, если в ответе есть hhcaptcha.captchaState
        (такое бывает и при 200, и при 403).
        """
        try:
            res = r.json()
        except JSONDecodeError:
            return {"text": r.text, "http_status": r.status_code}

        if not isinstance(res, dict):
            # Их говноапи может и список вернуть и null
            res = {"data": res}

        if captcha_state := (res.get("hhcaptcha") or {}).get("captchaState"):
            raise CaptchaError(captcha_state)

        # В res["recaptcha"]["key"] всегда лежит ключ, но не ясно, что еще должно быть, чтобы ошибку рекапчи бросить...

        res.setdefault("http_status", r.status_code)
        return res

    @staticmethod
    def _with_captcha(
        json: dict | None,
        data: dict | None,
        captcha: dict,
    ) -> tuple[dict | None, dict | None]:
        """Подмешивает поля капчи в json (если он есть) или в form-data."""
        if json is not None:
            return {**json, **captcha}, data
        return json, {**(data or {}), **captcha}

    # --- Запросы ------------------------------------------------------------

    def _xhr_request(
        self,
        method: str,
        endpoint: str,
        params: dict | None = None,
        data: dict | None = None,
        json: dict | None = None,
        referer_url: str | None = None,
        additional_headers: dict | None = None,
        xsrf_token: str | None = None,
        session: requests.Session | None = None,
    ) -> XHRResult:
        """Одна попытка XHR-запроса к внутреннему API hh.ru (без решения капчи).

        endpoint            -- путь ("/shards/...") или полный URL (например, chatik.hh.ru).
        params              -- query string (и для GET, и для POST/PUT).
        data                -- тело запроса (form-data).
        json                -- тело запроса (JSON).
        referer_url         -- страница, с которой "сделан" запрос. Если не передан,
                               берётся главная того же хоста.
        additional_headers  -- дополнительные заголовки; перекрывают стандартные.
        xsrf_token          -- если не передан, берётся из куки _xsrf сессии.

        Статус ответа НЕ проверяется: код возвращается в поле "http_status".
        Бросает CaptchaError, если сервер потребовал капчу, и ValueError,
        если нет токена _xsrf.
        """
        session = session or self.session
        url = urljoin(self.base_url, endpoint)

        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"

        xsrf = xsrf_token or session.cookies.get("_xsrf")
        if not xsrf:
            raise ValueError("Нет куки _xsrf: сначала авторизуйтесь")

        request_headers = self._build_xhr_headers(
            origin=origin,
            xsrf=xsrf,
            referer_url=referer_url or f"{origin}/",
            extra_headers=additional_headers or {},
        )

        r = session.request(
            method.upper(),
            url,
            params=params,
            data=data,
            json=json,
            headers=request_headers,
            allow_redirects=False,
            timeout=(10, 30),
        )

        logger.debug(
            "XMLHttpRequest: %s %s %d", r.request.method, r.url, r.status_code
        )
        return self._parse_xhr_response(r)

    def xhr_request(
        self,
        method: str,
        endpoint: str,
        params: dict | None = None,
        data: dict | None = None,
        json: dict | None = None,
        referer_url: str | None = None,
        additional_headers: dict | None = None,
        xsrf_token: str | None = None,
        session: requests.Session | None = None,
    ) -> XHRResult:
        """XHR-запрос с автоматическим решением капчи.

        Параметры те же, что у `_xhr_request`. При CaptchaError решает капчу
        и повторяет запрос, но не более MAX_CAPTCHA_ATTEMPTS раз.
        """
        for attempt in range(MAX_CAPTCHA_ATTEMPTS + 1):
            try:
                return self._xhr_request(
                    method,
                    endpoint,
                    params=params,
                    data=data,
                    json=json,
                    referer_url=referer_url,
                    additional_headers=additional_headers,
                    xsrf_token=xsrf_token,
                    session=session,
                )
            except CaptchaError as ex:
                if not self.handle_captcha:
                    raise

                if attempt >= MAX_CAPTCHA_ATTEMPTS:
                    raise

                logger.debug(
                    "(%d/%d) Требуется ввод капчи: %s %s",
                    attempt + 1,
                    MAX_CAPTCHA_ATTEMPTS,
                    method,
                    endpoint,
                )

                with self.captcha_retry_delay():
                    solution = self.solve_captcha(
                        captcha_state=ex.state,
                        referer_url=referer_url,
                    )
                json, data = self._with_captcha(
                    json,
                    data,
                    {
                        "captchaState": ex.state,
                        "captchaText": solution.text,
                        "captchaKey": solution.key,
                    },
                )

        raise AssertionError("unreachable")

    @contextmanager
    def captcha_retry_delay(self):
        """Время задержки после решения капчи будет расти в прогрессии"""
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - start
            delay = random.uniform(
                CAPTCHA_SOLVE_MIN_DELAY, CAPTCHA_SOLVE_MAX_DELAY
            )
            remaining = delay - elapsed
            if remaining > 0:
                logger.debug("Wait before retry after captcha: %.2f", remaining)
                time.sleep(remaining)

    def get_captcha_image(
        self,
        *,
        lang: str | None = None,
        xsrf_token: str | None = None,
        referer_url: str | None = None,
        session: requests.Session | None = None,
    ) -> CaptchaImage:
        session = session or self.session
        lang = lang or self.captcha_lang

        target_url = urljoin(referer_url or self.base_url, "/captcha")
        logger.debug(
            "Отправляем POST-запрос на %s для получения captcha key", target_url
        )

        res = self._xhr_request(
            "POST",
            target_url,
            params={"lang": lang},
            referer_url=referer_url,
            additional_headers=_CAPTCHA_HEADERS,
            xsrf_token=xsrf_token,
            session=session,
        )
        captcha_key = res["key"]

        image_url = urljoin(
            target_url, "/captcha/picture?key=" + quote(captcha_key)
        )
        logger.debug("Пробуем загрузить капчу: %s", image_url)

        # Это не XHR: браузер грузит картинку из тега IMG с другим Accept
        # и без XHR-заголовков, поэтому здесь обычный session.get.
        headers = _ACCEPT_IMAGE_HEADERS.copy()
        if referer_url:
            headers |= {"Referer": referer_url}

        image_data = session.get(image_url, headers=headers).content

        assert len(image_data) > 0, "Ошибка загрузки изображения"

        return CaptchaImage(data=image_data, key=captcha_key)

    def _send_captcha(
        self,
        text: str,
        key: str,
        state: str,
        referer_url: str | None = None,
        xsrf_token: str | None = None,
        backurl: str | None = None,
        session: requests.Session | None = None,
    ) -> bool:
        """Отправляет введенную капчу."""

        captcha_endpoint = "/account/captcha"
        target_url = urljoin(referer_url or self.base_url, captcha_endpoint)

        failurl = captcha_endpoint + "?state=" + quote(state)
        if backurl:
            failurl += "&backurl=" + quote(backurl)

        payload = {
            "captchaText": text,
            "captchaKey": key,
            "captchaState": state,
            "backurl": backurl or "/",
            "failurl": failurl,
        }

        logger.debug(f"POST {target_url}: {payload=}")

        # payload уходит в query string, тело пустое (так делает браузер).
        # Редиректы xhr_request не выполняет: при успехе 302 ведёт на hh://...,
        # такую схему requests не умеет, а сам редирект не нужен.
        try:
            res = self._xhr_request(
                "POST",
                target_url,
                params=payload,
                referer_url=referer_url,
                additional_headers=_CAPTCHA_HEADERS,
                xsrf_token=xsrf_token,
                session=session,
            )
            logger.debug("%.300s", res)
            return True
        except Error:
            return False

    def prompt_captcha_tkinter(self, image_data: bytes) -> str:
        """Показывает капчу в окне Tk и возвращает введённый текст.

        Если окно закрыли, не введя текст, бросает KeyboardInterrupt.
        """
        placeholder = "Введите текст с картинки"
        result: list[str] = []

        root = tk.Tk()
        root.title("Капча")
        root.resizable(False, False)
        root.attributes("-topmost", True)

        frame = ttk.Frame(root, padding=12)
        frame.pack()

        # Ряд 1: картинка
        photo = tk.PhotoImage(data=base64.b64encode(image_data))
        image_label = ttk.Label(frame, image=photo)
        image_label.image = photo  # держим ссылку, иначе картинку удалит GC
        image_label.pack(pady=(0, 8))

        # Ряд 2: поле ввода с плейсхолдером
        entry = ttk.Entry(frame, width=30, justify="center", foreground="grey")
        entry.insert(0, placeholder)
        entry.pack(fill="x", pady=(0, 8))

        def on_focus_in(_event):
            if str(entry.cget("foreground")) == "grey":
                entry.delete(0, "end")
                entry.configure(foreground="black")

        def on_focus_out(_event):
            if not entry.get():
                entry.insert(0, placeholder)
                entry.configure(foreground="grey")

        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)

        # Ряд 3: кнопка
        def submit(_event=None):
            text = entry.get().strip()
            if not text or str(entry.cget("foreground")) == "grey":
                return  # пусто или остался плейсхолдер
            result.append(text)
            root.destroy()

        ttk.Button(frame, text="Отправить", command=submit).pack(fill="x")
        root.bind("<Return>", submit)
        root.bind("<Escape>", lambda _e: root.destroy())

        # Центрируем окно на экране
        root.update_idletasks()
        x = (root.winfo_screenwidth() - root.winfo_width()) // 2
        y = (root.winfo_screenheight() - root.winfo_height()) // 2
        root.geometry(f"+{x}+{y}")

        root.focus_force()
        root.mainloop()

        return (result or [""])[0]

    def logout(self) -> None:
        self.session.get(f"{self.base_url}/logout", {"hhtmFrom": "main"})

        # Она всегда 302 возвращает, даже если ты не авторизован
        # узнать вышел ли ты нельзя
        # logger.debug("/logout %d", r.status_code)

        # Затираем куки
        self.session.cookies.clear()

        # И отзываем токен
        try:
            self.api_client.delete("/oauth/token")
        finally:
            self.api_client.reset_tokens()

    @cached_property
    def captcha_ai(self) -> ai.OpenAIChat:
        return self.ai_chat_for(
            "openai.captcha",
            system_prompt=(
                "You read CAPTCHA images. Return ONLY the text from the "
                "image, exactly as it is written."
            ),
        )

    @staticmethod
    def _format_experience(
        experience: list[dict[str, Any]] | None, limit: int = 3
    ) -> str:
        blocks = []
        for exp in (experience or [])[:limit]:
            end = exp.get("end") or "по настоящее время"
            head = "\n".join(
                filter(
                    None,
                    [
                        exp.get("position"),
                        exp.get("company"),
                        f"{exp.get('start') or ''} - {end}",
                    ],
                )
            )
            # Не надо в описании поэмы писать
            description = shorten(
                (exp.get("description") or "").strip(),
                limit=1000,
            )
            blocks.append(f"{head}\n\n{description}".strip())
        return "\n\n".join(blocks)

    def get_resume_placeholders(self, resume_id: str) -> ResumePlaceholders:
        """Данные резюме для подстановки в шаблон промпта AI-фильтра."""

        resume: api.datatypes.Resume = self.api_client.get(
            f"/resumes/{resume_id}"
        )

        # logger.debug("resume: %r", resume)

        rv = {
            k: v
            for k, v in resume.items()
            if k in ["first_name", "middle_name", "last_name"]
        }

        rv["resume_title"] = resume.get("title") or ""
        rv["resume_city"] = resume.get("area", {}).get("name") or ""
        # Почему тут ебаут?
        rv["resume_about"] = resume.get("skills") or ""
        rv["resume_skills"] = ", ".join(resume.get("skill_set") or [])
        rv["resume_employment_form"] = ", ".join(
            i["name"] for i in (resume.get("employment_form") or [])
        )
        rv["resume_work_format"] = ", ".join(
            i["name"] for i in (resume.get("work_format") or [])
        )
        rv["resume_citizenship"] = ", ".join(
            i["name"] for i in resume.get("citizenship") or []
        )
        salary = resume.get("salary") or {}
        amount = salary.get("amount") or 0
        currency = (
            (salary.get("currency") or "")
            .replace("RUR", "руб.")
            .replace("USD", "$")
        )
        rv["resume_salary"] = f"{amount} {currency}".strip()
        education = resume.get("education") or {}

        try:
            primary_education = education["primary"][0]
        except (KeyError, IndexError):
            primary_education = {}

        rv["resume_education"] = ", ".join(
            filter(
                None,
                [
                    # высшее/среднее
                    education.get("level", {}).get("name"),
                    # Шарага
                    primary_education.get("name"),
                    # Факультет
                    primary_education.get("organization"),
                    # Специальность
                    primary_education.get("result"),
                    # Год
                    str(primary_education.get("year") or ""),
                ],
            )
        )

        rv["resume_experience"] = self._format_experience(
            resume.get("experience") or []
        )
        rv["resume_total_experience"] = self._format_total_expirience(
            resume.get("total_experience", {}).get("months") or 0
        )
        return rv

    @staticmethod
    def _format_total_expirience(months: int) -> str:
        if not months:
            return "без опыта"
        years, rest = divmod(months, 12)
        return f"{years} г. {rest} мес."

    def _save_token(self, token: dict[str, Any]) -> None:
        self.token_config.update(token=token)
        self.token_config.save()
        logger.info("Token saved: %s", self.token_config.path)

    def create_config_dir(self) -> None:
        self.config_dir_path.mkdir(
            parents=True,
            exist_ok=True,
        )

    def setup_logging(
        self,
        verbosity: int | None = None,
    ):
        if verbosity is not None:
            self.verbosity = verbosity
        # Создаем путь до директории с логами
        verbosity_level = max(
            logging.DEBUG, logging.WARNING - self.verbosity * 10
        )
        setup_logger(logger, verbosity_level, self.log_file)
        setup_terminal()

    def _assign_args(self, args: BaseNamespace) -> None:
        for k, v in vars(args).items():
            setattr(self, k, v)

    def run(self, argv: Sequence[str] | None = None) -> None | int:
        args = self._parser.parse_args(argv, namespace=BaseNamespace())
        self._assign_args(args)
        self.create_config_dir()
        self.setup_logging()
        if is_docker():
            logger.info("Запущено через Docker")
        logger.debug("Путь до профиля: %s", self.config_dir_path)

        if not self.operation_run:
            self._parser.print_help(file=sys.stderr)
            return 2

        def on_sigterm(signum, frame):
            raise KeyboardInterrupt

        # Костыль для докер
        signal.signal(signal.SIGTERM, on_sigterm)

        try:
            return self.operation_run(self, args)
        except (OperationCanceled, KeyboardInterrupt, EOFError):
            logger.warning("Выполнение операции прервано пользователем!")
            return 130
        except OperationError as ex:
            logger.error(ex)
        except Exception as ex:
            logger.exception(ex)
        finally:
            try:
                self.save_cookies()
            except Exception as ex:
                logger.error(f"Не удалось сохранить cookies: {ex}")

        return 1


HHApplicantTool.__doc__ = """Утилита для автоматизации действий соискателя на сайте hh.ru.

Исходники и предложения: <{repo_url}>

Группа поддержки: <{tg_url}>""".format(
    repo_url=GITHUB_REPO_URL,
    tg_url=TELEGRAM_CHAT_URL,
)
