from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import smtplib
import sqlite3
import sys
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from http.cookiejar import MozillaCookieJar
from importlib import import_module
from itertools import count
from os import getenv
from pathlib import Path
from pkgutil import iter_modules
from typing import Any, Callable, Iterable, Type, TypedDict
from urllib.parse import parse_qsl, urljoin, urlsplit

import requests

from . import ai, api, utils
from .constants import (
    CONFIG_DIR,
    CONFIG_FILENAME,
    COOKIES_FILENAME,
    DATABASE_FILENAME,
    DEFAULT_CAPTCHA_LANGUAGE,
    DEFAULT_OPENAI_CONNECT_TIMEOUT,
    DEFAULT_OPENAI_TIMEOUT,
    DESKTOP_USER_AGENT,
    LOG_FILENAME,
)
from .storage import StorageFacade
from .utils.argparse import ArgumentFormatter
from .utils.cookiejar import HHOnlyCookieJar
from .utils.log import setup_logger
from .utils.mixins import MegaTool
from .utils.terminal import print_kitty_image, print_sixel_image

logger = logging.getLogger(__package__)

OPERATIONS = "operations"


class HHLuxInitialState(TypedDict):
    redirectConfig: dict[str, Any]
    ...


class CaptchaInfo:
    url: str
    key: str
    url: str
    lang: str
    image_data: bytes


class Error(Exception):
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


class BaseAttrs:
    profile_id: str
    config_dir: Path
    verbosity: int
    api_delay: float
    user_agent: str
    proxy_url: str
    use_sixel: bool
    use_kitty: bool
    manual: bool
    captcha_lang: str
    captcha_attempts: int
    openai_proxy_url: str
    openai_timeout: float
    openai_connect_timeout: float


class BaseNamespace(argparse.Namespace, BaseAttrs):
    operation_run: Callable[[HHApplicantTool, BaseNamespace], None | int] | None


@dataclass
class BaseAPICaptchaHandler(ABC):
    tool: HHApplicantTool

    @abstractmethod
    def __call__(self, captcha_url: str) -> bool:
        """Этот метод обязан переопределить каждый наследник."""
        pass


class APICaptchaHandler(BaseAPICaptchaHandler):
    def __call__(self, captcha_url: str) -> bool:
        return (
            self.tool.solve_captcha_manual(captcha_url)
            if self.tool.manual
            else self.tool.solve_captcha_ai(captcha_url)
        )


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
            "-m",
            "--manual",
            action="store_true",
            help="Ручной режим ввода (капчи)",
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

    def __init__(
        self,
        *,
        captcha_handler_class: Type[BaseAPICaptchaHandler] | None = None,
    ):
        self._parser = self._create_parser()
        self._captcha_handler_class = captcha_handler_class

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
        return self._get_proxies()

    def _create_http_session(
        self,
        proxies: dict[str, str],
        *,
        log_label: str,
    ) -> requests.Session:
        session = requests.Session()

        if proxies:
            logger.info("Use proxies for %s: %r", log_label, proxies)
            session.proxies = proxies

        session.headers.update({"User-Agent": DESKTOP_USER_AGENT})
        return session

    @cached_property
    def session(self) -> HHSession:
        session = self._create_http_session(
            self._get_proxies(),
            log_label="requests",
        )

        session.cookies = HHOnlyCookieJar(str(self.cookies_file))
        if self.cookies_file.exists():
            session.cookies.load(ignore_discard=True, ignore_expires=True)

        return session

    @cached_property
    def openai_session(self) -> requests.Session:
        return self._create_http_session(
            self._get_openai_proxies(),
            log_label="OpenAI requests",
        )

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
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
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
            captcha_handler=self._captcha_handler_class(self)
            if self._captcha_handler_class
            else None,
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
        self, response: requests.Response, check_auth: bool = True
    ) -> HHLuxInitialState:
        """Возвращает декодированное содержимое <template id="HH-Lux-InitialState"></template>"""
        if response.status_code != 200:
            raise Error(
                f"Неожиданный код ответа: {response.status_code} {response.url}"
            )

        try:
            raw_data = response.text.split('id="HH-Lux-InitialState">')[
                1
            ].split("</template>")[0]
        except IndexError as ex:
            raise Error(
                f"Template with initial state data not found on {response.url}"
            ) from ex

        # Теперь кавычки всегда превращаются в сущности?
        if raw_data.startswith("{&#34;"):
            raw_data = html.unescape(raw_data)

        # import tempfile
        # with tempfile.NamedTemporaryFile('w', delete=False, prefix='hh_initial_state_', suffix='.json', dir='.', encoding='utf-8') as tmp_file:
        #     tmp_file.write(raw_data)
        #     file_path = tmp_file.name
        #     print(file_path)

        data = json.loads(raw_data)
        assert type(data) is dict
        assert "redirectConfig" in data
        if check_auth and not self._is_authenticated(data):
            raise Error("Авторизация истекла требуется новая!")

        return data

    def fetch_initial_state(
        self, url: str, check_auth: bool = True
    ) -> HHLuxInitialState:
        return self.parse_initial_state(self.session.get(url), check_auth)

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

    def get_ai_client(
        self,
        system_prompt: str,
        purpose: str | None = None,
    ) -> ai.ChatOpenAI:
        config_sections = {
            "cover_letter": "openai_cover_letter",
            "vacancy_filter": "openai_vacancy_filter",
            "captcha": "openai_captcha",
            "chat": "openai_chat",
        }

        c = self.config.get("openai", {})

        if purpose is not None:
            if purpose not in config_sections:
                raise ValueError(
                    f"Неизвестная цель AI: {purpose}. "
                    f"Допустимые значения: {list(config_sections.keys())}"
                )

            purpose_config = self.config.get(config_sections[purpose], {})
            # Переписываем значения openai
            c = {**c, **purpose_config}

        api_key = c.get("api_key")
        if not api_key:
            raise ValueError(
                "API-ключ не задан. Укажите 'api_key' в секции 'openai'"
                + (f" или '{config_sections[purpose]}'." if purpose else ".")
            )

        base_url = c.get("base_url")
        if not base_url:
            raise ValueError(
                "Параметр 'base_url' не задан. Укажите его в секции 'openai'"
                + (f" или '{config_sections[purpose]}'." if purpose else ".")
            )

        model = c.get("model")
        if not model:
            logger.warning(
                "Параметр 'model' не задан в конфигурации."
                + (
                    f" Секции 'openai' и '{config_sections[purpose]}' не содержат "
                    "этого параметра."
                    if purpose
                    else " Секция 'openai' не содержит этого параметра."
                )
            )

        return ai.ChatOpenAI(
            api_key=api_key,
            model=model,
            temperature=c.get("temperature", 0.0),
            max_completion_tokens=c.get("max_completion_tokens", 1000),
            system_prompt=system_prompt,
            base_url=base_url,
            rate_limit=c.get("rate_limit", 40),
            timeout=(
                self.openai_timeout
                or c.get("timeout")
                or DEFAULT_OPENAI_TIMEOUT
            ),
            connect_timeout=(
                self.openai_connect_timeout
                or c.get("connect_timeout")
                or DEFAULT_OPENAI_CONNECT_TIMEOUT
            ),
            session=self.openai_session,
        )

    # TODO: вынести в миксин какой
    def get_cookie(self, name: str) -> str | None:
        """Значение cookie по имени из jar на базе {CookieJar} (нет get_dict)."""
        return next(
            (c.value for c in self.session.cookies if c.name == name),
            None,
        )

    def _extract_xsrf_token(self, content: str) -> str:
        # hh.ru отдает этот блок с HTML-заэкранированными кавычками
        # (внутри HTML-атрибута), поэтому сначала разэкранируем всю страницу
        content = html.unescape(content)
        tokens = re.findall(r',"xsrfToken":"([^"]+)"', content)
        if not tokens:
            raise ValueError("xsrf token not found")

        # На странице hh.ru может быть несколько xsrfToken. Первый из них —
        # случайное значение, которое ротируется при каждой загрузке и НЕ
        # соответствует cookie `_xsrf`, из-за чего POST на
        # /applicant/vacancy_response/popup возвращал 403 (CSRF mismatch).
        # Сервер сверяет токен именно с cookie `_xsrf`, поэтому отдаем
        # совпадающее значение, а не первое вхождение.
        cookie_xsrf = self.get_cookie("_xsrf")
        if cookie_xsrf and cookie_xsrf in tokens:
            return cookie_xsrf
        return tokens[0]

    def _get_xsrf_token(self, url: str | None = None) -> str:
        """Возвращает XSRF-токен, который выдается на сессию."""
        # Токен, который сервер реально валидирует, лежит в cookie `_xsrf`.
        # Если cookie уже есть — используем его и не делаем лишний GET.
        cookie_xsrf = self.get_cookie("_xsrf")
        if cookie_xsrf:
            return cookie_xsrf
        r = self.session.get(url or "https://hh.ru/")
        return self._extract_xsrf_token(r.text)

    @cached_property
    def xsrf_token(self) -> str:
        return self._get_xsrf_token()

    @property
    def is_logged_in(self) -> bool:
        """Проверяет авторизован ли пользователь через сайт."""
        return self.session.get("https://hh.ru/settings").status_code == 200

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

    def _fetch_captcha(
        self, captcha_url: str, lang: str = DEFAULT_CAPTCHA_LANGUAGE
    ) -> CaptchaInfo:
        """Получает изображение в виде набора байт. Вторым аргументом можно передать язык"""
        captcha_state = dict(parse_qsl(urlsplit(captcha_url).query))["state"]

        logger.debug("Получаем куки со страницы: %s", captcha_url)
        # Предполагаю, что на этой странице кука какая-то ставится
        r = self.session.get(captcha_url)
        r.raise_for_status()

        # Тут пока ничего не нужно как заглушка используется
        data = self.parse_initial_state(r)
        logger.debug("Initial State Keys:  %s", ", ".join(*data))
        assert data["hhcaptcha"]["captchaState"] == captcha_state

        # Страница, где каптча показывается
        # Обычно редиректит на страницу города
        referer_url = r.url

        # Потом кука используется для получения captcha key
        captcha_key_url = urljoin(referer_url, "/captcha?lang=" + lang)
        logger.debug(
            "Отправляем POST-запрос на %s для получения captcha key",
            captcha_key_url,
        )
        js = self.session.post(
            captcha_key_url,
            headers={
                "Referer": referer_url,
                "X-Xsrftoken": self.xsrf_token,
                "x-hhtmfrom": "",
                "x-hhtmsource": "account_captcha",
                # Я тут опустил кучу заголовков, так как их значения есть в
                # кукис, и сайт, если тех нет, берех их от туда
                # Те запрос проходит
                "X-Requested-With": "XMLHttpRequest",
            },
        ).json()

        captcha_key = js["key"]

        captcha_image_url = urljoin(
            referer_url, "/captcha/picture?key=" + captcha_key
        )

        logger.debug("Пробуем загрузить каптчу: %s", captcha_image_url)
        # А с помощью captcha key получаем изображение
        captcha_image_data = self.session.get(
            captcha_image_url, headers={"Referer": referer_url}
        ).content

        assert len(captcha_image_data) > 0, "Ошибка загрузки изображения"

        return {
            "key": captcha_key,
            "image_data": captcha_image_data,
            "state": captcha_state,
            "url": referer_url,
            "lang": lang,
        }

    def _send_captcha(self, url: str, text: str, key: str, state: str) -> bool:
        target_url: str = urljoin(url, "/account/captcha")

        payload = {
            "captchaText": text,
            "captchaKey": key,
            "captchaState": state,
            # Я не уверен, что эти параметры обзяательные
            "backurl": "/",
            "fialurl": target_url + "?state=" + state,
        }

        # Там зачем-то payload передается и в теле запроса и в query string
        # Скорее всего его можно передать только в теле
        r = self.session.post(
            target_url,
            params=payload,
            data=payload,
            headers={
                "Referer": url,
                "X-Requested-With": "XMLHttpRequest",
                "X-Xsrftoken": self.xsrf_token,
                "x-hhtmfrom": "",
                "x-hhtmsource": "account_captcha",
            },
        )

        logger.debug(
            "Код ответа сервера на отправку текста каптчи: %d", r.status_code
        )
        return r.status_code == 200

    def solve_captcha_manual(self, captcha_url: str) -> bool:
        assert self.use_kitty or self.use_sixel, (
            "Для ручного решения каптчи нужно использовать один из флагов: --use-sixel/--use-kitty"
        )
        try:
            while True:
                captcha = self._fetch_captcha(captcha_url, self.captcha_lang)
                if self.use_kitty:
                    print_kitty_image(captcha["image_data"])
                else:
                    print_sixel_image(captcha["image_data"])
                text = input("Введите текст с картинки выше: ")
                if self._send_captcha(
                    captcha["url"], text, captcha["key"], captcha["state"]
                ):
                    return True
                print("Попробуй еще!")
        except (KeyboardInterrupt, EOFError):
            return False

    @cached_property
    def captcha_ai(self) -> ai.ChatOpenAI:
        return self.get_captcha_ai()

    def solve_captcha_ai(self, captcha_url: str) -> bool:
        for attempt in range(1, self.captcha_attempts + 1):
            logger.debug(
                "(%d/%d) try to solve captcha: %s",
                attempt,
                self.captcha_attempts,
                captcha_url,
            )
            captcha = self._fetch_captcha(captcha_url, self.captcha_lang)
            text = self.captcha_ai.recognize_text(captcha["image_data"])
            logger.debug("AI answer for %s: %s", captcha_url, text)
            if self._send_captcha(
                captcha["url"], text, captcha["key"], captcha["state"]
            ):
                logger.debug("Captcha accepted for %s", captcha_url)
                return True
        logger.warning("Can't solve captcha for %s", captcha_url)
        return False

    def run(self, argv: Sequence[str] | None = None) -> None | int:
        args = self._parser.parse_args(argv, namespace=BaseNamespace())
        self._assign_args(args)

        # Создаем путь до конфига
        self.config_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        verbosity_level = max(
            logging.DEBUG,
            logging.WARNING - self.verbosity * 10,
        )

        setup_logger(logger, verbosity_level, self.log_file)

        logger.debug("Путь до профиля: %s", self.config_path)

        utils.setup_terminal()

        try:
            if not self.operation_run:
                self._parser.print_help(file=sys.stderr)
                return 2
            return self._run_operation(args)
        finally:
            self._check_system()

    def _run_operation(self, args: BaseNamespace) -> None | int:
        """Запускает выбранную операцию и превращает исключения в сообщения."""
        try:
            return self.operation_run(self, args)
        except KeyboardInterrupt:
            logger.warning("Выполнение прервано пользователем!")
        except api.errors.CaptchaRequired as ex:
            logger.error(f"Требуется ввод капчи: {ex.captcha_url}")
        except api.errors.InternalServerError:
            logger.error(
                "Сервер HH.RU не смог обработать запрос из-за высокой"
                " нагрузки или по иной причине"
            )
        except api.errors.Forbidden:
            logger.error("Требуется авторизация")
        except (Error, ValueError) as ex:
            logger.error(ex)
        except sqlite3.Error as ex:
            logger.exception(ex)

            script_name = sys.argv[0].split(os.sep)[-1]

            logger.warning(
                f"Возможно база данных повреждена, попробуйте выполнить команду:\n\n"  # noqa: E501
                f"  {script_name} migrate-db"
            )
        except Exception as e:
            logger.exception(e)
        finally:
            # Токен мог автоматически обновиться
            if self.save_token():
                logger.info("Токен был сохранен после обновления.")

            try:
                self.save_cookies()
            except Exception as ex:
                logger.error(f"Не удалось сохранить cookies: {ex}")
        return 1

    def _assign_args(self, args: BaseNamespace) -> None:
        for name, value in vars(args).items():
            setattr(self, name, value)
