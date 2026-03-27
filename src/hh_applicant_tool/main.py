from __future__ import annotations

import argparse
import logging
import os
import smtplib
import sqlite3
import sys
from collections.abc import Sequence
from functools import cached_property
from http.cookiejar import MozillaCookieJar
from importlib import import_module
from itertools import count
from os import getenv
from pathlib import Path
from pkgutil import iter_modules
from typing import Any, Callable, Iterable

import requests
import urllib3

from . import ai, api, utils
from .constants import (
    CONFIG_DIR,
    CONFIG_FILENAME,
    COOKIES_FILENAME,
    DATABASE_FILENAME,
    DESKTOP_USER_AGENT,
    LOG_FILENAME,
)
from .storage import StorageFacade
from .utils.cookiejar import HHOnlyCookieJar
from .utils.log import setup_logger
from .utils.mixins import MegaTool

logger = logging.getLogger(__package__)

OPERATIONS = "operations"


class BaseOperation:
    def setup_parser(self, parser: argparse.ArgumentParser) -> None: ...

    def run(
        self,
        tool: HHApplicantTool,
        args: BaseNamespace,
    ) -> None | int:
        raise NotImplementedError()


class BaseNamespace(argparse.Namespace):
    profile_id: str
    config_dir: Path
    verbosity: int
    api_delay: float
    user_agent: str
    proxy_url: str
    openai_proxy_url: str
    operation_run: Callable[[HHApplicantTool, BaseNamespace], None | int] | None


class HHApplicantTool(MegaTool):
    """Утилита для автоматизации действий соискателя на сайте hh.ru.

    Исходники и предложения: <https://github.com/s3rgeym/hh-applicant-tool>

    Группа поддержки: <https://t.me/hh_applicant_tool>
    """

    class ArgumentFormatter(
        argparse.ArgumentDefaultsHelpFormatter,
        argparse.RawDescriptionHelpFormatter,
    ):
        pass

    @classmethod
    def _create_parser(cls) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description=cls.__doc__,
            formatter_class=cls.ArgumentFormatter,
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
                formatter_class=cls.ArgumentFormatter,
            )
            op_parser.set_defaults(operation_run=op.run)
            op.setup_parser(op_parser)
        parser.set_defaults(operation_run=None)
        return parser

    def __init__(self):
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
        return self._get_proxies()

    def _create_http_session(
        self,
        proxies: dict[str, str],
        *,
        log_label: str,
    ) -> requests.Session:
        session = requests.Session()
        session.verify = False

        if proxies:
            logger.info("Use proxies for %s: %r", log_label, proxies)
            session.proxies = proxies

        session.headers.update({"User-Agent": DESKTOP_USER_AGENT})
        return session

    @cached_property
    def session(self) -> requests.Session:
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
        
        return self._init_ai_client(system_prompt, purpose="cover_letter")


    def get_vacancy_filter_ai(self, system_prompt: str) -> ai.ChatOpenAI:
    
        return self._init_ai_client(system_prompt, purpose="vacancy_filter")


    def _init_ai_client(self, system_prompt: str, purpose: str) -> ai.ChatOpenAI:

        config_sections = {
            "cover_letter": "openai_cover_letter",
            "vacancy_filter": "openai_vacancy_filter",
        }
        
        if purpose not in config_sections:
            raise ValueError(
                f"Неизвестная цель AI: {purpose}. "
                f"Допустимые значения: {list(config_sections.keys())}"
            )
        
        config_section = config_sections[purpose]
        c = self.config.get(config_section, {})
        
        api_key = c.get("api_key")
        if not api_key:
            raise ValueError(
                f"API-ключ не задан. Укажите 'api_key' в секции '{config_section}' конфигурации."
            )

        base_url = c.get("base_url")
        if not base_url:
            raise ValueError(
                f"Параметр 'base_url' обязателен для AI-конфигурации в секции '{config_section}'. "
                "Примеры: OpenAI='https://api.openai.com/v1/chat/completions', "
                "Ollama='http://localhost:11434/v1/chat/completions', "
                "OpenRouter='https://openrouter.ai/api/v1/chat/completions'"
            )

        model = c.get("model")
        if not model:
            logger.warning(
                "Параметр 'model' не задан в секции '%s'. "
                "Большинство AI-провайдеров (OpenAI, OpenRouter) требуют указания модели. "
                "Примеры: 'gpt-4o-mini', 'gpt-3.5-turbo', 'openai/gpt-4'",
                config_section,
            )
    
        return ai.ChatOpenAI(
            api_key=api_key,
            model=model,
            temperature=c.get("temperature", 0.0),
            max_completion_tokens=c.get("max_completion_tokens", 1000),
            system_prompt=system_prompt,
            base_url=base_url,
            rate_limit=c.get("rate_limit", 40),
            session=self.openai_session,
        )

    # TODO: вынести в миксин какой
    def _extract_xsrf_token(self, content: str) -> str:
        xsrf_token_marker = ',"xsrfToken":"'
        s1 = content.find(xsrf_token_marker)
        if s1 == -1:
            raise ValueError("xsrf token not found")
        s1 += len(xsrf_token_marker)
        s2 = content.find('"', s1)
        if s2 == -1:
            raise ValueError("malformed xsrf token")
        return content[s1:s2]

    def _get_xsrf_token(self, url: str | None = None) -> str:
        """Возвращает XSRF-токен, который выдается на сессию"""
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
            if self.operation_run:
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
                except ValueError as ex:
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
            self._parser.print_help(file=sys.stderr)
            return 2
        finally:
            try:
                self._check_system()
            except Exception:
                pass
                # raise

    def _assign_args(self, args: BaseNamespace) -> None:
        for name, value in vars(args).items():
            setattr(self, name, value)


def main(argv: Sequence[str] | None = None) -> None | int:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return HHApplicantTool().run(argv)
