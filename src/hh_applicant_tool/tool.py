from __future__ import annotations

import argparse
import copy
import html
import json
import logging
import re
import smtplib
import sys
import time
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import KW_ONLY, dataclass
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

from hh_applicant_tool.utils.package import PACKAGE_NAME

from . import ai, api
from .constants import (
    ACCEPT_LANGUAGE,
    ANDROID_CLIENT_ID,
    ANDROID_CLIENT_SECRET,
    ANDROID_WEBVIEW_USERAGENT,
    AUTH_CONFIG_FILENAME,
    CAPTCHA_SUCCESS_BACKURL,
    CONFIG_DIR,
    CONFIG_FILENAME,
    COOKIES_FILENAME,
    DEFAULT_CAPTCHA_LANGUAGE,
    DEFAULT_DESKTOP_USERAGENT,
    HH_BASE_URL,
    LOG_FILENAME,
    REPO_URL,
)
from .errors import Error, OperationCanceled, OperationError
from .utils.argparse import ArgumentFormatter
from .utils.config import ConfigJSON, ConfigTOML
from .utils.helpers import get_proxies_dict
from .utils.log import setup_logger
from .utils.system import has_gui_support, is_docker
from .utils.term import print_kitty_image, print_sixel_image, setup_terminal
from .utils.user_agent import generate_android_useragent

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


@dataclass
class HHApplicantTool:
    """Утилита для автоматизации действий соискателя на сайте hh.ru.

    Исходники и предложения: <https://github.com/s3rgeym/hh-applicant-tool>

    Группа поддержки: <https://t.me/s3rgeym_chat>
    """

    _: KW_ONLY
    api_delay: float | None = None
    base_url: str | None = None
    captcha_manual: bool = False
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
            choices=["RU", "EN"],
            help="Язык капчи. Некоторые модели распознают лучше текст на английском",
        )
        parser.add_argument(
            "--captcha-manual",
            "--manual",
            help="Ручной ввод капчи. Полезен, если модель не поддерживает vision",
            action="store_true",
            default=False,
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
        user_agent: str | None = None,
        proxies: dict[str, str] | None = None,
    ) -> requests.Session:
        session = requests.Session()
        if proxies is None:
            proxies = get_proxies_dict(self.proxy_url)

        if proxies:
            logger.debug("session proxies: %r", proxies)
            session.proxies = proxies

        # В заголовки не лезь, если не понимаешь зачем они
        session.headers.update(
            {
                "User-Agent": user_agent or self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": ACCEPT_LANGUAGE,
            }
        )

        logger.debug("session headers: %r", session.headers)

        return session

    @cached_property
    def session(self) -> requests.Session:
        session = self._create_session()

        if self.cookies_file.exists():
            jar = MozillaCookieJar(str(self.cookies_file))
            jar.load(ignore_discard=True, ignore_expires=True)
            session.cookies.update(jar)

        # Запоминаем куки, которые были при инициализации
        self._original_cookies = list(session.cookies)
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
                "User-Agent": f"{PACKAGE_NAME} (+{REPO_URL})",
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
    def auth_config(self) -> ConfigJSON:
        return ConfigJSON(self.config_dir_path / AUTH_CONFIG_FILENAME)

    @cached_property
    def log_file(self) -> Path:
        return self.config_dir_path / LOG_FILENAME

    @cached_property
    def cookies_file(self) -> Path:
        return self.config_dir_path / COOKIES_FILENAME

    # def get_section_config(self, section: str) -> dict:
    #     keys = section.split(".")
    #     current = self.config
    #     parents = []
    #
    #     for key in keys:
    #         if not isinstance(current, dict) or key not in current:
    #             break
    #
    #         current = current[key]
    #
    #         if isinstance(current, dict):
    #             parents.append(current)
    #
    #     if not parents:
    #         return {}
    #
    #     result = deepcopy(parents[-1])
    #
    #     for parent in reversed(parents[:-1]):
    #         for key, value in parent.items():
    #             result.setdefault(key, deepcopy(value))
    #
    #     return result

    @cached_property
    def api_client(self) -> api.client.ApiClient:
        token = self.auth_config.get("token", self.config.get("token", {}))
        client_config = self.config.get("api_client", {}).copy()
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
            captcha_handler=self.handle_captcha,
            **client_config,
        )

        self._original_token = client.get_access_token()
        return client

    def get_ai_client(
        self,
        system_prompt: str | None = None,
        **kwargs,
    ) -> ai.ChatOpenAI:
        kwargs.setdefault("session", self.ai_session)
        return ai.ChatOpenAI(system_prompt=system_prompt, **kwargs)

    def get_openai_config(self, section: str | None = None) -> dict:
        """Возвращает копию конфига openai с учетом наследования от главной"""
        base_section = "openai"
        default_section = "default"
        if section is None:
            section = default_section
        elif "." in section:
            base, section = section.split(".")
            if base != base_section:
                raise ValueError(
                    f"Base section must be {base_section!r}: got: {base!r}"
                )

        # if not re.fullmatch(r"[a-z]+", section):
        #     raise ValueError(f"Bad {base_section!r} section name: {section!r}")

        def required(name: str) -> None:
            if name not in c:
                raise ValueError(
                    f"Значение {name!r} не задано в [{base_section}.{section}]"
                    + (
                        f" или [{base_section}.{default_section}]"
                        if section != default_section
                        else ""
                    )
                )

        c = self.config.get(base_section) or {}
        c = deepcopy(
            {
                **(c.get("default") or {}),
                **(c.get(section) or {}),
            }
        )

        required("base_url")
        # required("api_key")
        required("model")

        if self.openai_delay:
            c.setdefault("delay", self.openai_delay)
        if self.openai_timeout:
            c.setdefault("timeout", self.openai_timeout)
        if self.openai_connect_timeout:
            c.setdefault("connect_timeout", self.openai_connect_timeout)

        return c

    def get_openai_settings(self, config_section: str = None) -> dict:
        c = self.get_openai_config(section=config_section)
        return {
            k: v
            for k, v in c.items()
            if k
            in [
                "api_key",
                "base_url",
                "chat_completions_endpoint",
                "connect_timeout",
                "delay",
                "history",
                "max_completion_tokens",
                "max_retries",
                "model",
                "proxy_url",
                "system_prompt",
                "temperature",
                "timeout",
            ]
        }

    def _get_captcha_ai(self) -> ai.ChatOpenAI:
        c = self.get_openai_settings("openai.captcha")
        c.setdefault(
            "system_prompt",
            (
                "You read CAPTCHA images. Return ONLY the text from the "
                "image, exactly as it is written."
            ),
        )
        return self.get_ai_client(**c)

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

    def save_token(self) -> bool:
        # Методы API не вызывались
        if not hasattr(self, "_original_token"):
            return False

        token = self.api_client.get_access_token()

        # Поля токена не изменились
        if token == self._original_token:
            return False

        self.auth_config.save(token=token)
        self._original_token = token
        return True

    def save_cookies(self) -> None:
        """Сохраняет cookies сессии hh в файл."""
        if not hasattr(self, "_original_cookies"):
            return

        jar = MozillaCookieJar(str(self.cookies_file))
        for c in self.session.cookies:
            if c.domain and not re.search(
                r"^((?:.*?\.)?hh\.(ru|kz|uz|by|net|com)|rabota\.by)\.?$",
                c.domain,
            ):
                continue

            jar.set_cookie(copy.copy(c))

        current_cookies = list(jar)
        if self._original_cookies == current_cookies:
            return

        jar.save(ignore_discard=True, ignore_expires=True)
        self._original_cookies = current_cookies
        logger.debug("Cookies saved to %s", self.cookies_file)

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
            return self.captcha_ai.recognize_text(image_data)

        if not has_gui_support() or self.use_kitty or self.use_sixel:
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

        return CaptchaSolution(
            text=text,
            state=captcha_state,
            key=captcha_img.key,
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

        # Создадим новую пустую сессию для прохождения капчи
        session = self._create_session(user_agent=ANDROID_WEBVIEW_USERAGENT)

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

    def get_captcha_image(
        self,
        *,
        lang: str | None = None,
        xsrf_token: str | None = None,
        referer_url: str | None = None,
        session: requests.Session | None = None,
    ) -> CaptchaImage:
        if session is None:
            session = self.session
        xsrf_token = xsrf_token or session.cookies.get("_xsrf")

        lang = lang or self.captcha_lang
        target_url = urljoin(
            referer_url or self.base_url, "/captcha?lang=" + quote(lang)
        )
        logger.debug(
            "Отправляем POST-запрос на %s для получения captcha key",
            target_url,
        )
        res = session.post(
            target_url,
            headers={
                k: v
                for k, v in {
                    "Accept": "application/json",
                    "Referer": referer_url,
                    "X-Xsrftoken": xsrf_token,
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

        # Браузер когда встречает в разметке тег IMG, посылает другой Accept
        headers = {
            "Accept": "image/avif,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5"
        }

        if referer_url:
            headers |= {"Referer": referer_url}

        image_data = session.get(
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
        backurl: str | None = None,
        session: requests.Session | None = None,
    ) -> bool:
        """Отправляет введенную капчу."""

        captcha_endpoint = "/account/captcha"
        target_url: str = urljoin(
            referer_url or self.base_url, captcha_endpoint
        )

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

        headers = {
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-Xsrftoken": xsrf_token,
            "x-hhtmfrom": "",
            "x-hhtmsource": "account_captcha",
        }

        if referer_url:
            headers |= {"Referer": referer_url}

        logger.debug(f"POST {target_url}: {payload=}, {headers=}")

        # payload уходит в query string, тело пустое (так делает браузер).
        # allow_redirects=False: при успехе 302 ведёт на hh://..., такую
        # схему requests не умеет, а нам сам редирект не нужен.
        r = session.post(
            target_url,
            params=payload,
            headers=headers,
            allow_redirects=False,
        )

        logger.debug(f"{r.request.method} {r.request.url} {r.status_code}")

        if r.status_code == 302:
            return True

        if r.status_code == 403:
            return False

        # Произошло что-то странное
        logger.warning(
            "Неожиданный код ответа на отправку капчи: %d", r.status_code
        )
        logger.debug(r.text[:255])
        return False

    def prompt_captcha_tk(self, image_data: bytes) -> str:
        """Показывает капчу в окне Tk и возвращает введённый текст.

        Если окно закрыли, не введя текст, бросает KeyboardInterrupt.
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
        # if not result:
        #     raise KeyboardInterrupt()

        # Пусть падает.
        # Правильное решение тут только дать случиться неизбежному.
        return result[0].strip()

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
    def captcha_ai(self) -> ai.ChatOpenAI:
        return self._get_captcha_ai()

    def create_config_dir(self) -> None:
        self.config_dir_path.mkdir(
            parents=True,
            exist_ok=True,
        )

    def _save_config_if_needed(self) -> None:
        """Нужен для сохранения загруженного конфига в старом формате в новом"""
        if self.config and not self.config.exists():
            self.config.save()

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

        try:
            return self.operation_run(self, args)
        except (OperationCanceled, KeyboardInterrupt, EOFError):
            logger.warning("Выполнение операции прервано пользователем!")
            return 130
        except OperationError as ex:
            logger.error(ex)
        except Exception as ex:
            logger.exception(ex)

        # Токен мог автоматически обновиться
        if self.save_token():
            logger.debug("Токен был сохранен после обновления.")

        try:
            self.save_cookies()
        except Exception as ex:
            logger.error(f"Не удалось сохранить cookies: {ex}")

        self._save_config_if_needed()
        return 1
