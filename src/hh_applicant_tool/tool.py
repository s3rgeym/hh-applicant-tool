from __future__ import annotations

import argparse
import html
import json
import logging
import re
import smtplib
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from http.cookiejar import MozillaCookieJar
from importlib import import_module
from itertools import count
from os import getenv
from pathlib import Path
from pkgutil import iter_modules
from typing import Any, Callable, ClassVar, Iterable, NamedTuple, TypedDict
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

from . import ai, api, utils
from .constants import (
    ACCEPT,
    ACCEPT_LANGUAGE,
    BROWSER_USER_AGENT,
    CONFIG_DIR,
    CONFIG_FILENAME,
    COOKIES_FILENAME,
    DATABASE_FILENAME,
    DEFAULT_CAPTCHA_LANGUAGE,
    DEFAULT_OPENAI_CONNECT_TIMEOUT,
    DEFAULT_OPENAI_TIMEOUT,
    HH_BASE_URL,
    LOG_FILENAME,
    REPO_URL,
)
from .mixins import MegaTool
from .storage import StorageFacade
from .utils.argparse import ArgumentFormatter
from .utils.cookiejar import HHOnlyCookieJar
from .utils.log import setup_logger
from .utils.package import PACKAGE_NAME, get_package_version
from .utils.terminal import print_kitty_image, print_sixel_image

logger = logging.getLogger(__package__)

OPERATIONS = "operations"


class HHLuxInitialState(TypedDict):
    redirectConfig: dict[str, Any]
    ...


class CaptchaImage(NamedTuple):
    key: str
    url: str
    data: bytes
    lang: str


class Error(Exception):
    pass


# Используй эту ошибку для прерывания выполнения команд
class OperationError(Exception):
    pass


class BaseOperation:
    def setup_parser(self, parser: argparse.ArgumentParser) -> None: ...

    def run(
        self,
        tool: HHApplicantTool,
        args: BaseNamespace,  # pyright: ignore[reportUnusedParameter]
    ) -> None | int:
        raise NotImplementedError()


class HHSession(requests.Session):
    cookies: HHOnlyCookieJar


@dataclass
class BaseAttrs:
    profile_id: str | None = None
    config_dir: Path | None = None
    verbosity: int = 0
    api_delay: float | None = None
    user_agent: str | None = None
    proxy_url: str | None = None
    use_sixel: bool = False
    use_kitty: bool = False
    use_ai: bool = False
    captcha_lang: str = DEFAULT_CAPTCHA_LANGUAGE
    captcha_attempts: int = 3
    openai_proxy_url: str | None = None
    openai_timeout: float | None = None
    openai_connect_timeout: float | None = None


class BaseNamespace(argparse.Namespace, BaseAttrs):
    operation_run: Callable[[HHApplicantTool, BaseNamespace], None | int] | None


# Сначала это мне показалось хорошей идеей, потом понял, что лишние сущности
# @dataclass
# class BaseAPICaptchaHandler(ABC):
#     tool: HHApplicantTool
#
#     @abstractmethod
#     def __call__(self, captcha_url: str) -> bool:
#         """Этот метод обязан переопределить каждый наследник."""
#         pass
#
#
# class APICaptchaHandler(BaseAPICaptchaHandler):
#     def __call__(self, captcha_url: str) -> bool:
#         return (
#             self.tool.solve_captcha_manual(captcha_url)
#             if self.tool.manual
#             else self.tool.solve_captcha_ai(captcha_url)
#         )


@dataclass
class HHApplicantTool(MegaTool, BaseAttrs):
    """Утилита для автоматизации действий соискателя на сайте hh.ru.

    Исходники и предложения: <https://github.com/s3rgeym/hh-applicant-tool>

    Группа поддержки: <https://t.me/s3rgeym_chat>
    """

    @classmethod
    def _create_parser(cls) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description=cls.__doc__,
            formatter_class=ArgumentFormatter,
            argument_default=argparse.SUPPRESS,
        )
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
            default=None,
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
            "--user-agent",
            help="User-Agent для каждого запроса",
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
            "--openai-timeout",
            "--ai-timeout",
            type=float,
            help="Таймаут запроса к OpenAI в секундах: соединение и чтение ответа",
        )
        parser.add_argument(
            "--openai-connect-timeout",
            "--ai-connect-timeout",
            type=float,
            help="Таймаут соединения с OpenAI в секундах",
        )
        parser.add_argument(
            "--use-ai",
            "--ai",
            action="store_true",
            default=False,
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
            default=DEFAULT_CAPTCHA_LANGUAGE,
            help="Язык капчи. Некоторые модели распознают лучше текст на английском",
        )
        parser.add_argument(
            "--captcha-attempts",
            default=3,
            help="Максимальное количество неудачных попыток автоматического распознания капчи",
        )
        subparsers = parser.add_subparsers(help="commands")
        package_dir = Path(__file__).resolve().parent / OPERATIONS
        for _, module_name, _ in iter_modules([str(package_dir)]):
            if module_name.startswith("_"):
                continue
            mod = import_module(f"{__package__}.{OPERATIONS}.{module_name}")
            op: BaseOperation = mod.Operation()
            kebab_name = module_name.replace("_", "-")
            op_parser = subparsers.add_parser(
                kebab_name,
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

    @staticmethod
    def _proxy_url_to_dict(proxy_url: str | None) -> dict[str, str]:
        if not proxy_url:
            return {}

        return {
            "http": proxy_url,
            "https": proxy_url,
        }

    def _get_proxies(self) -> dict[str, str]:
        proxy_url = self.proxy_url or self.config.get("proxy_url")

        if proxy_url:
            return self._proxy_url_to_dict(proxy_url)

        proxies = {}
        http_env = getenv("HTTP_PROXY") or getenv("http_proxy")
        https_env = getenv("HTTPS_PROXY") or getenv("https_proxy") or http_env

        if http_env:
            proxies["http"] = http_env
        if https_env:
            proxies["https"] = https_env

        return proxies

    def _get_openai_proxies(self) -> dict[str, str]:
        openai_config = self.config.get("openai", {})
        proxy_url = self.openai_proxy_url or openai_config.get("proxy_url")
        if proxy_url:
            return self._proxy_url_to_dict(proxy_url)
        # Из какого-нибудь казахстана одинаково hh и ChatGPT работают
        return self._get_proxies()

    def _create_browser_session(
        self,
        proxies: dict[str, str] | None = None,
    ) -> requests.Session:
        session = requests.Session()

        if proxies:
            logger.info("Use proxies for Browser: %r", proxies)
            session.proxies = proxies

        # В заголовки не лезь, если не понимаешь зачем они
        session.headers.update(
            {
                "User-Agent": BROWSER_USER_AGENT,
                "Accept": ACCEPT,
                "Accept-Language": ACCEPT_LANGUAGE,
            }
        )

        logger.debug("Browser Session Headers: %r", session.headers)

        return session

    @cached_property
    def session(self) -> HHSession:
        session = self._create_browser_session(
            self._get_proxies(),
        )

        session.cookies = HHOnlyCookieJar(str(self.cookies_file))
        if self.cookies_file.exists():
            session.cookies.load(ignore_discard=True, ignore_expires=True)

        return session

    @staticmethod
    def get_tool_useragent() -> str:
        return f"{PACKAGE_NAME}/{get_package_version()} (+{REPO_URL})"

    @cached_property
    def openai_session(self) -> requests.Session:
        session = requests.session()

        if proxies := self._get_openai_proxies():
            session.proxies = proxies

        session.headers.update({"User-Agent": self.get_tool_useragent()})

        logger.debug("OpenAI Session Headers: %r", session.headers)

        return session

    @cached_property
    def config_path(self) -> Path:
        return (
            (self.config_dir or Path(getenv("CONFIG_DIR", CONFIG_DIR)))
            / (self.profile_id or getenv("HH_PROFILE_ID", "."))
        ).resolve()

    @cached_property
    def config(self) -> utils.Config:
        return utils.Config(self.config_path / CONFIG_FILENAME)

    @cached_property
    def log_file(self) -> Path:
        return self.config_path / LOG_FILENAME

    @cached_property
    def cookies_file(self) -> Path:
        return self.config_path / COOKIES_FILENAME

    @cached_property
    def db_path(self) -> Path:
        return self.config_path / DATABASE_FILENAME

    @cached_property
    def db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        return conn

    @cached_property
    def storage(self) -> StorageFacade:
        return StorageFacade(self.db)

    @cached_property
    def api_client(self) -> api.client.ApiClient:
        config = self.config
        token = config.get("token", {})
        return api.client.ApiClient(
            client_id=config.get("client_id"),
            client_secret=config.get("client_secret"),
            access_token=token.get("access_token"),
            refresh_token=token.get("refresh_token"),
            access_expires_at=token.get("access_expires_at"),
            delay=self.api_delay or config.get("api_delay"),
            user_agent=self.user_agent or config.get("user_agent"),
            session=self.session,
            captcha_handler=self.solve_captcha_url,
        )

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

    def _is_authenticated(self, config: dict[str, Any]) -> bool:
        account = config.get("account") or {}
        if not account:
            return False
        # Если пользователь неавторизован содержит поля типа firstName, lastName и тд со значением None (все поля)
        return any(v is not None for v in account.values())

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

    # TODO: добавить еще методов или те удалить?

    def save_token(self) -> bool:
        if self.api_client.access_token != self.config.get("token", {}).get(
            "access_token"
        ):
            self.config.save(token=self.api_client.get_access_token())
            return True
        return False

    def save_cookies(self) -> None:
        """Сохраняет текущие куки сессии в файл."""
        if isinstance(self.session.cookies, MozillaCookieJar):
            self.session.cookies.save(ignore_discard=True, ignore_expires=True)
            logger.debug("Cookies saved to %s", self.cookies_file)
        else:
            logger.warning(
                f"Сессионные куки имеют неправильный тип: {type(self.session.cookies)}"
            )

    def get_cover_letter_ai(self, system_prompt: str) -> ai.ChatOpenAI:
        return self.get_ai_client(system_prompt, purpose="cover_letter")

    def get_vacancy_filter_ai(self, system_prompt: str) -> ai.ChatOpenAI:
        return self.get_ai_client(system_prompt, purpose="vacancy_filter")

    def get_chat_ai(self, system_prompt: str) -> ai.ChatOpenAI:
        return self.get_ai_client(system_prompt, purpose="chat")

    def get_captcha_ai(self) -> ai.ChatOpenAI:
        return self.get_ai_client(
            system_prompt=(
                "You read CAPTCHA images. Return ONLY the text from the "
                "image, exactly as it is written."
            ),
            purpose="captcha",
        )

    OPENAI_ADDITIONAL_SECTIONS: ClassVar[list[str]] = [
        "cover_letter",
        "vacancy_filter",
        "captcha",
        "chat",
    ]

    def has_openai_config(self) -> bool:
        if "openai" in self.config:
            return True
        return any(
            key.startswith("openai_")
            and key[len("openai_") :] in self.OPENAI_ADDITIONAL_SECTIONS
            for key in self.config
        )

    def get_ai_client(
        self,
        system_prompt: str,
        purpose: str | None = None,
    ) -> ai.ChatOpenAI:
        config: dict = self.config.get("openai", {})

        # Переменные окружения имеют более низкий приоритет
        config.setdefault("base_url", getenv("HH_AI_BASE_URL"))
        config.setdefault("api_key", getenv("HH_AI_API_KEY"))
        config.setdefault("model", getenv("HH_AI_MODEL"))

        section_name: str | None = None

        if purpose is not None:
            if purpose not in self.OPENAI_ADDITIONAL_SECTIONS:
                raise ValueError(
                    f"Неизвестная название доп секции `openai`: {purpose}. "
                    f"Допустимые значения: {self.OPENAI_ADDITIONAL_SECTIONS}"
                )

            section_name = f"openai_{purpose}"
            purpose_config = self.config.get(section_name, {})
            # Переписываем значения openai
            config = {**config, **purpose_config}

        if (api_key := config.get("api_key")) is None:
            raise ValueError(
                "API-ключ не задан. Укажите 'api_key' в секции 'openai'"
                + (f" или {section_name!r}" if section_name else "")
            )

        if (base_url := config.get("base_url")) is None:
            raise ValueError(
                "Параметр 'base_url' не задан. Укажите его в секции 'openai'"
                + (f" или {section_name!r}" if section_name else "")
            )

        if (model := config.get("model")) is None:
            raise ValueError(
                "Параметр 'model' не задан в конфигурации."
                + (
                    f" Секции 'openai' и '{section_name}' не содержат этого параметра."
                    if section_name
                    else " Секция 'openai' не содержит этого параметра."
                )
            )

        return ai.ChatOpenAI(
            api_key=api_key,
            model=model,
            temperature=config.get("temperature") or 0.0,
            max_completion_tokens=config.get("max_completion_tokens") or 1000,
            system_prompt=system_prompt,
            base_url=base_url,
            timeout=(
                self.openai_timeout
                or config.get("timeout")
                or DEFAULT_OPENAI_TIMEOUT
            ),
            connect_timeout=(
                self.openai_connect_timeout
                or config.get("connect_timeout")
                or DEFAULT_OPENAI_CONNECT_TIMEOUT
            ),
            session=self.openai_session,
        )

    # TODO: вынести в миксин какой
    def get_cookie(self, name: str, default: Any = None) -> str | None:
        """Значение cookie по имени из jar на базе {CookieJar} (нет get_dict)."""
        return next(
            (c.value for c in self.session.cookies if c.name == name),
            default,
        )

    # Удалить
    def _extract_xsrf_token(self, content: str) -> str:
        # hh.ru отдает этот блок с HTML-заэкранированными кавычками
        # (внутри HTML-атрибута), поэтому сначала разэкранируем всю страницу
        content = html.unescape(content)
        tokens = re.findall(r',"xsrfToken":"([^"]+)"', content)
        if not tokens:
            raise ValueError("xsrf token not found")

    @property
    def xsrf_token(self) -> str | None:
        return self.get_cookie("_xsrf")

    @property
    def base_url(self) -> str:
        return (
            "https://"
            + self.get_cookie("redirect_host", HH_BASE_URL)
            .split("://", 1)[-1]
            .split("/")[0]
        )

    @property
    def is_logged_in(self) -> bool:
        """Проверяет авторизован ли пользователь через сайт."""
        return self.session.get(f"{self.base_url}/settings").status_code == 200

    @cached_property
    def smtp(self) -> smtplib.SMTP | smtplib.SMTP_SSL:
        conf = self.config.get("smtp", {})
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

    def _solve_captcha(
        self,
        image_data: bytes,
        captcha_state: str,
        captcha_key: str,
        referer_url: str | None = None,
    ) -> bool:
        if self.use_ai:
            captcha_text = self.captcha_ai.recognize_text(image_data)
        else:
            if self.use_kitty or self.use_sixel:
                if self.use_kitty:
                    print_kitty_image(image_data)
                else:
                    print_sixel_image(image_data)
                captcha_text = input("Введите текст с картинки выше: ").strip()
            else:
                captcha_text = self.prompt_captcha_tk(image_data)

        return self.send_captcha(
            text=captcha_text,
            state=captcha_state,
            key=captcha_key,
            referer_url=referer_url,
        )

    def solve_captcha(
        self,
        captcha_state: str,
        *,
        lang: str | None = None,
        referer_url: str | None = None,
        xsrf_token: str | None = None,
    ) -> bool:
        """Если API сайта возвращает ответ с hhcaptcha.captchaState, то
        появляется всплывающее окно для ввода капчи"""
        captcha_img = self.get_captcha_image(
            lang=lang, referer_url=referer_url, xsrf_token=xsrf_token
        )
        return self._solve_captcha(
            image_data=captcha_img.data,
            captcha_state=captcha_state,
            captcha_key=captcha_img.key,
            referer_url=referer_url,
        )

    def solve_captcha_url(
        self,
        captcha_url: str,
        *,
        lang: str | None = None,
        referer_url: str | None = None,
        xsrf_token: str | None = None,
    ) -> bool:
        """Отдельная страница с капчей"""
        captcha_state = parse_qs(urlsplit(captcha_url).query)["state"][0]

        headers = {}
        if referer_url:
            headers["Referer"] = referer_url

        # Посещаем страницу с капчей
        r = self.session.get(captcha_url, headers=headers)
        r.raise_for_status()

        return self.solve_captcha(
            captcha_state=captcha_state,
            lang=lang,
            xsrf_token=xsrf_token,
            referer_url=r.url,
        )

    def get_captcha_image(
        self,
        *,
        lang: str | None = None,
        xsrf_token: str | None = None,
        referer_url: str | None = None,
    ) -> CaptchaImage:
        lang = lang or self.captcha_lang
        target_url = urljoin(HH_BASE_URL, "/captcha?lang=" + lang)
        logger.debug(
            "Отправляем POST-запрос на %s для получения captcha key",
            target_url,
        )
        res = self.session.post(
            target_url,
            headers={
                k: v
                for k, v in {
                    "Referer": referer_url,
                    "X-Xsrftoken": xsrf_token or self.xsrf_token,
                    "x-hhtmfrom": "",
                    "x-hhtmsource": "account_captcha",
                    # Я тут опустил кучу заголовков, так как их значения есть в
                    # кукис, и сайт, если тех нет, берех их от туда
                    # Те запрос проходит
                    "X-Requested-With": "XMLHttpRequest",
                }.items()
                if v is not None
            },
        ).json()

        captcha_key = res["key"]

        image_url = urljoin(HH_BASE_URL, "/captcha/picture?key=" + captcha_key)
        logger.debug("Пробуем загрузить капчу: %s", image_url)

        headers = {}

        if referer_url:
            headers |= {"Referer": referer_url}

        image_data = self.session.get(
            image_url,
            headers=headers,
        ).content

        assert len(image_data) > 0, "Ошибка загрузки изображения"

        return CaptchaImage(
            data=image_data,
            key=captcha_key,
            lang=lang,
            url=image_url,
        )

    def send_captcha(
        self,
        text: str,
        key: str,
        state: str,
        referer_url: str | None = None,
    ) -> bool:
        captcha_endpoint = "/account/captcha"
        target_url: str = urljoin(HH_BASE_URL, captcha_endpoint)

        payload = {
            "captchaText": text,
            "captchaKey": key,
            "captchaState": state,
            # Я не уверен, что эти параметры обзяательные
            "backurl": "/",
            "fialurl": captcha_endpoint + "?state=" + state,
        }

        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-Xsrftoken": self.xsrf_token,
            "x-hhtmfrom": "",
            "x-hhtmsource": "account_captcha",
        }

        if referer_url:
            headers |= {"Referer": referer_url}

        logger.debug(f"POST {target_url}: {payload=}, {headers=}")

        # Там зачем-то payload передается и в теле запроса и в query string
        # Скорее всего его можно передать только в теле
        r = self.session.post(
            target_url,
            params=payload,
            headers=headers,
        )

        logger.debug(
            "Код ответа сервера на отправку текста капчи: %d", r.status_code
        )

        # При вводе неверной капчи показывает Forbidden
        return r.status_code != 403

    def prompt_captcha_tk(self, image_data: bytes) -> str:
        """Показывает капчу в окне Tk и возвращает введённый текст.

        Если окно закрыли, не введя текст, бросает KeyboardInterrupt,
        чтобы solve_captcha_manual корректно завершился.
        """
        import base64
        import tkinter as tk
        from tkinter import ttk

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

        # Окно было закрыто
        if not result:
            raise KeyboardInterrupt()

        return result[0]

    @cached_property
    def captcha_ai(self) -> ai.ChatOpenAI:
        return self.get_captcha_ai()

    def setup_logging(
        self,
        verbosity: int | None = None,
        log_file: str | Path | None = None,
    ):
        if verbosity is not None:
            self.verbosity = verbosity
        if log_file is not None:
            self.log_file = log_file
        # Создаем путь до директории с логами
        self.config_path.mkdir(
            parents=True,
            exist_ok=True,
        )
        verbosity_level = max(
            logging.DEBUG, logging.WARNING - self.verbosity * 10
        )
        setup_logger(logger, verbosity_level, self.log_file)
        utils.setup_terminal()

    def run(self, argv: Sequence[str] | None = None) -> None | int:
        args = self._parser.parse_args(argv, namespace=BaseNamespace())
        self._assign_args(args)
        self.setup_logging()
        logger.debug("Путь до профиля: %s", self.config_path)

        try:
            if not self.operation_run:
                self._parser.print_help(file=sys.stderr)
                return 2
            return self.operation_run(self, args)
        except KeyboardInterrupt:
            logger.warning("Выполнение прервано пользователем!")
        except OperationError as ex:
            logger.error(ex)
        except Exception as ex:
            logger.exception(ex)
        finally:
            # Токен мог автоматически обновиться
            if self.save_token():
                logger.info("Токен был сохранен после обновления.")

            try:
                self.save_cookies()
            except Exception as ex:
                logger.error(f"Не удалось сохранить cookies: {ex}")

            self._check_system()

        return 1

    def _assign_args(self, args: BaseNamespace) -> None:
        for name, value in vars(args).items():
            setattr(self, name, value)
