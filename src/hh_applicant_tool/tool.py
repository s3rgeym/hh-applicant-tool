from __future__ import annotations

import argparse
import html
import json
import logging
import smtplib
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cached_property
from http.cookiejar import MozillaCookieJar
from importlib import import_module
from itertools import count
from os import getenv
from pathlib import Path
from pkgutil import iter_modules
from typing import Any, Callable, Iterable, Literal, NamedTuple, TypedDict
from urllib.parse import parse_qs, quote, urljoin, urlsplit

import requests

from . import ai, api, utils
from .constants import (
    ACCEPT_LANGUAGE,
    CONFIG_DIR,
    CONFIG_FILENAME,
    COOKIES_FILENAME,
    DATABASE_FILENAME,
    DEFAULT_CAPTCHA_LANGUAGE,
    DEFAULT_DESKTOP_USERAGENT,
    HH_BASE_URL,
    LOG_FILENAME,
    REPO_URL,
)
from .errors import Error, OperationCanceled, OperationError
from .storage import StorageFacade
from .utils.argparse import ArgumentFormatter
from .utils.cookiejar import HHOnlyCookieJar
from .utils.log import setup_logger
from .utils.package import PACKAGE_NAME, get_package_version, parse_version
from .utils.system import is_docker
from .utils.terminal import print_kitty_image, print_sixel_image

logger = logging.getLogger("hh-applicant-tool")

OPERATIONS = "operations"


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


class HHSession(requests.Session):
    cookies: HHOnlyCookieJar


@dataclass
class BaseAttrs:
    profile_id: str | None = None
    config_dir: Path | None = None
    verbosity: int = 0
    api_delay: float | None = None
    user_agent: str | None = DEFAULT_DESKTOP_USERAGENT
    proxy_url: str | None = None
    use_sixel: bool = False
    use_kitty: bool = False
    use_ai: bool = False
    captcha_lang: str = DEFAULT_CAPTCHA_LANGUAGE
    openai_proxy_url: str | None = None
    openai_delay: float | None = None
    openai_timeout: float | None = None
    openai_connect_timeout: float | None = None


class BaseNamespace(argparse.Namespace, BaseAttrs):
    operation_run: Callable[[HHApplicantTool, BaseNamespace], None | int] | None


@dataclass
class HHApplicantTool(BaseAttrs):
    """Утилита для автоматизации действий соискателя на сайте hh.ru.

    Исходники и предложения: <https://github.com/s3rgeym/hh-applicant-tool>

    Группа поддержки: <https://t.me/s3rgeym_chat>
    """

    @classmethod
    def _create_parser(cls) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description=cls.__doc__,
            formatter_class=ArgumentFormatter,
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
            help="User-Agent для запросов к HH. Нужно притворяться каким-нибудь популярным браузером, иначе будет показывать 403 или 404 ошибку на каждый запрос",
            default=DEFAULT_DESKTOP_USERAGENT,
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
            choices=["RU", "EN"],
            help="Язык капчи. Некоторые модели распознают лучше текст на английском",
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
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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

    def get_openai_session(self) -> requests.Session:
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
            # Это просто тест капчи, если передать браузерный юзер-агент, она
            # сработает
            # user_agent=self.user_agent,
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

    def get_captcha_ai(self) -> ai.ChatOpenAI:
        return self.get_ai_client(
            system_prompt=(
                "You read CAPTCHA images. Return ONLY the text from the "
                "image, exactly as it is written."
            ),
            purpose="captcha",
        )

    # def has_openai_config(self) -> bool:
    #     if "openai" in self.config:
    #         return True
    #     return any(key.startswith("openai_") for key in self.config)

    def get_ai_client(
        self,
        purpose: str | None = None,
        *,
        delay: float | None = None,
        system_prompt: str | None = None,
    ) -> ai.ChatOpenAI:
        config: dict = self.config.get("openai", {})

        # Значения из конфигов имеют больший приоритет
        config.setdefault("system_prompt", system_prompt)
        config.setdefault("delay", delay or self.openai_delay)
        config.setdefault("timeout", self.openai_timeout)
        config.setdefault("connect_timeout", self.openai_connect_timeout)
        config.setdefault("base_url", getenv("HH_AI_BASE_URL"))
        config.setdefault("api_key", getenv("HH_AI_API_KEY"))
        config.setdefault("model", getenv("HH_AI_MODEL"))

        section_name: str | None = None

        if purpose is not None:
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
            base_url=base_url,
            connect_timeout=config["connect_timeout"],
            delay=config["delay"],
            max_completion_tokens=config.get("max_completion_tokens"),
            model=model,
            session=self.get_openai_session(),
            system_prompt=config["systemp_prompt"],
            temperature=config.get("temperature"),
            timeout=config["timeout"],
        )

    # TODO: вынести в миксин какой
    def get_cookie(self, name: str, default: Any = None) -> str | None:
        """Значение cookie по имени из jar на базе {CookieJar} (нет get_dict)."""
        return next(
            (c.value for c in self.session.cookies if c.name == name),
            default,
        )

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

    def _solve_captcha(self, image_data: bytes) -> str:
        if self.use_ai:
            return self.captcha_ai.recognize_text(image_data)

        if self.use_kitty or self.use_sixel:
            if self.use_kitty:
                print_kitty_image(image_data)
            else:
                print_sixel_image(image_data)
            return input("\nВведите текст с картинки выше: ").strip()

        return self.prompt_captcha_tk(image_data)

    def solve_captcha(
        self,
        captcha_state: str,
        *,
        lang: str | None = None,
        referer_url: str | None = None,
        xsrf_token: str | None = None,
    ) -> CaptchaSolution:
        """Если API сайта возвращает ответ с hhcaptcha.captchaState, то
        появляется всплывающее окно для ввода капчи"""
        captcha_img = self.get_captcha_image(
            lang=lang,
            referer_url=referer_url,
            xsrf_token=xsrf_token,
        )
        text = self._solve_captcha(image_data=captcha_img.data)

        return CaptchaSolution(
            text=text,
            state=captcha_state,
            key=captcha_img.key,
        )

    def solve_captcha_url(
        self,
        captcha_url: str,
        *,
        lang: str | None = None,
        referer_url: str | None = None,
        xsrf_token: str | None = None,
    ) -> CaptchaSolution:
        """Отдельная страница с капчей"""
        logger.debug("captcha url: %s", captcha_url)

        # Посещаем страницу с капчей
        r = self.session.get(
            captcha_url,
            headers={"Referer": referer_url} if referer_url else {},
        )
        r.raise_for_status()

        data = self.parse_initial_state(r)
        xsrf_token = xsrf_token or self.xsrf_token
        assert data["xsrfToken"] == xsrf_token, "xsrf токены не совпадают!"
        captcha_state = parse_qs(urlsplit(r.url).query)["state"][0]

        logger.debug("Передаем в качестве referer: %s", r.url)
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
        target_url = urljoin(
            referer_url or HH_BASE_URL, "/captcha?lang=" + quote(lang)
        )
        logger.debug(
            "Отправляем POST-запрос на %s для получения captcha key",
            target_url,
        )
        res = self.session.post(
            target_url,
            headers={
                k: v
                for k, v in {
                    "Accept": "application/json",
                    "Referer": referer_url,
                    "X-Xsrftoken": xsrf_token or self.xsrf_token,
                    "X-Hhtmfrom": "",
                    "X-Hhtmsource": "account_captcha",
                    # Я тут опустил кучу заголовков, так как их значения есть в
                    # кукис, и сайт, если тех нет, берех их от туда
                    # Те запрос проходит
                    "X-Requested-With": "XMLHttpRequest",
                }.items()
                if v is not None
            },
        ).json()

        captcha_key = res["key"]

        image_url = urljoin(
            target_url, "/captcha/picture?key=" + quote(captcha_key)
        )
        logger.debug("Пробуем загрузить капчу: %s", image_url)

        headers = {
            "Accept": "image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5"
        }

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
        )

    def _send_captcha(
        self,
        text: str,
        key: str,
        state: str,
        referer_url: str | None = None,
        xsrf_token: str | None = None,
    ) -> bool:
        captcha_endpoint = "/account/captcha"
        target_url: str = urljoin(referer_url or HH_BASE_URL, captcha_endpoint)

        payload = {
            "captchaText": text,
            "captchaKey": key,
            "captchaState": state,
            # Я не уверен, что эти параметры обзяательные
            "backurl": "/",
            "failurl": captcha_endpoint + "?state=" + quote(state),
        }

        headers = {
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-Xsrftoken": xsrf_token or self.xsrf_token,
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

        if r.status_code in (200, 302):
            logger.debug(r.text[:255])
            return True

        assert r.status_code == 403

        try:
            res = r.json()
            logger.debug(res)
            return not res["hhcaptcha"]["captchaError"]
        except json.JSONDecodeError:
            logger.debug(r.text[:255])
            return False

    def prompt_captcha_tk(self, image_data: bytes) -> str | None:
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

        return result[0].strip()

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

    def __get_latest_version(self) -> Literal[False] | str:
        try:
            response = self.session.get(
                "https://pypi.org/pypi/hh-applicant-tool/json", timeout=15
            )
            ver = response.json().get("info", {}).get("version")
            # logger.debug(ver)
            return ver
        except requests.RequestException:
            return False

    def _check_version(self) -> bool:
        if datetime.now().timestamp() >= self.storage.settings.get_value(
            "_next_version_check", 0
        ):
            if v := self.__get_latest_version():
                self.storage.settings.set_value("_latest_version", v)
                self.storage.settings.set_value(
                    "_next_version_check", datetime.now() + timedelta(hours=1)
                )

        if (
            latest_ver := self.storage.settings.get_value("_latest_version")
        ) and (cur_ver := get_package_version()):
            if parse_version(latest_ver) > parse_version(cur_ver):
                logger.warning(
                    "ТЕКУЩАЯ ВЕРСИЯ %s УСТАРЕЛА. РЕКОМЕНДУЕТСЯ ОБНОВИТЬ ЕЁ ДО ВЕРСИИ %s.",
                    cur_ver,
                    latest_ver,
                )

    def _check_system(self):
        if not self.storage.settings.get_value("disable_version_check", False):
            self._check_version()

    # Этот костыль используется в ui. Ему здесь не место
    def _assign_args(self, args: BaseNamespace) -> None:
        # Явное лучше неявного
        self.profile_id = args.profile_id
        self.config_dir = args.config_dir
        self.verbosity = args.verbosity
        self.api_delay = args.api_delay
        self.user_agent = args.user_agent
        self.proxy_url = args.proxy_url
        self.use_sixel = args.use_sixel
        self.use_kitty = args.use_kitty
        self.use_ai = args.use_ai
        self.captcha_lang = args.captcha_lang
        self.openai_proxy_url = args.openai_proxy_url
        self.openai_delay = args.openai_delay
        self.openai_timeout = args.openai_timeout
        self.openai_connect_timeout = args.openai_connect_timeout
        self.operation_run = args.operation_run

    def run(self, argv: Sequence[str] | None = None) -> None | int:
        args = self._parser.parse_args(argv, namespace=BaseNamespace())
        self._assign_args(args)
        self.setup_logging()
        if is_docker():
            logger.debug("Запущено через Docker")
        logger.debug("Путь до профиля: %s", self.config_path)

        try:
            if not self.operation_run:
                self._parser.print_help(file=sys.stderr)
                return 2
            return self.operation_run(self, args)
        except (KeyboardInterrupt, OperationCanceled):
            logger.warning("Выполнение операции прервано!")
            return 130
        except OperationError as ex:
            logger.error(ex)
        except Exception as ex:
            logger.exception(ex)
        finally:
            # Токен мог автоматически обновиться
            if self.save_token():
                logger.debug("Токен был сохранен после обновления.")

            try:
                self.save_cookies()
            except Exception as ex:
                logger.error(f"Не удалось сохранить cookies: {ex}")

            self._check_system()

        return 1
