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
from typing import Any, Iterable

import requests
import urllib3

from . import ai, api, utils
from .storage import StorageFacade
from .utils.cookiejar import HHOnlyCookieJar
from .utils.log import setup_logger
from .utils.mixins import MegaTool

DEFAULT_CONFIG_DIR = utils.get_config_path() / (__package__ or "").replace(
    "_", "-"
)
DEFAULT_CONFIG_FILENAME = "config.json"
DEFAULT_LOG_FILENAME = "log.txt"
DEFAULT_DATABASE_FILENAME = "data"
DEFAULT_COOKIES_FILENAME = "cookies.txt"
DEFAULT_DESKTOP_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"

logger = logging.getLogger(__package__)


class BaseOperation:
    # Категория для группировки в --help (например "Авторизация", "Резюме")
    __category__: str = "Прочее"

    def setup_parser(self, parser: argparse.ArgumentParser) -> None: ...

    def run(
        self,
        tool: HHApplicantTool,
    ) -> None | int:
        raise NotImplementedError()


OPERATIONS = "operations"


class BaseNamespace(argparse.Namespace):
    profile_id: str
    config_dir: Path
    verbosity: int
    delay: float
    user_agent: str
    proxy_url: str


class HHApplicantTool(MegaTool):
    """Утилита для автоматизации действий соискателя на сайте hh.ru.

    Исходники и предложения: <https://github.com/s3rgeym/hh-applicant-tool>

    Группа поддержки: <https://t.me/hh_applicant_tool>
    """

    class ArgumentFormatter(
        argparse.ArgumentDefaultsHelpFormatter,
        argparse.RawDescriptionHelpFormatter,
    ):
        """Форматтер: скрывает (default: None), сохраняет форматирование описаний.
        Также скрывает positional arguments с SUPPRESS-хелпом из вывода."""

        def _get_help_string(self, action: argparse.Action) -> str | None:
            help_str = action.help or ""
            # Показываем default только если он задан и не None
            if (
                "%(default)" not in help_str
                and action.default is not None
                and action.default is not argparse.SUPPRESS
                and action.option_strings
            ):
                help_str += " (по умолчанию: %(default)s)"
            return help_str

        def _format_action(self, action: argparse.Action) -> str:
            # Скрываем positional subparser-actions (команды — они в epilog)
            if not action.option_strings and isinstance(
                action, argparse._SubParsersAction
            ):
                return ""
            if action.help == argparse.SUPPRESS and not action.option_strings:
                return ""
            return super()._format_action(action)

        def _format_actions_usage(self, actions, groups) -> str:
            # Упрощаем usage — не показываем длинный список команд
            result = super()._format_actions_usage(actions, groups)
            # Убираем {cmd1,cmd2,...} из usage, заменяем на <команда>
            import re
            result = re.sub(r"\{[^}]{40,}\}", "<команда>", result)
            return result

    def _build_commands_help(
        self, ops: list[tuple[str, BaseOperation]]
    ) -> str:
        from collections import defaultdict

        groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for name, op in ops:
            category = getattr(op, "__category__", "Прочее")
            doc = (op.__doc__ or "").strip().splitlines()[0] if op.__doc__ else ""
            groups[category].append((name, doc))

        # Порядок групп
        order = [
            "Авторизация",
            "Резюме",
            "Отклики",
            "Конфигурация",
            "Утилиты",
            "Прочее",
        ]

        lines = [""]
        for group in order:
            if group not in groups:
                continue
            lines.append(f"{group}:")
            for name, doc in sorted(groups[group], key=lambda x: x[0]):
                lines.append(f"  {name:<22}  {doc}")
            lines.append("")

        # Группы не из order
        for group, items in groups.items():
            if group in order:
                continue
            lines.append(f"{group}:")
            for name, doc in sorted(items, key=lambda x: x[0]):
                lines.append(f"  {name:<22}  {doc}")
            lines.append("")

        lines.append("Подробнее: hh-applicant-tool <команда> --help")
        return "\n".join(lines)

    def _create_parser(self) -> argparse.ArgumentParser:
        ops: list[tuple[str, BaseOperation]] = []
        package_dir = Path(__file__).resolve().parent / OPERATIONS
        for _, module_name, _ in iter_modules([str(package_dir)]):
            if module_name.startswith("_"):
                continue
            mod = import_module(f"{__package__}.{OPERATIONS}.{module_name}")
            op: BaseOperation = mod.Operation()
            kebab_name = module_name.replace("_", "-")
            ops.append((kebab_name, op))

        commands_help = self._build_commands_help(ops)

        parser = argparse.ArgumentParser(
            description=self.__doc__,
            formatter_class=self.ArgumentFormatter,
            epilog=commands_help,
            add_help=True,
        )
        parser.add_argument(
            "-v",
            "--verbosity",
            help="Увеличивает детализацию вывода (можно повторять: -vvv)",
            action="count",
            default=0,
        )
        parser.add_argument(
            "-c",
            "--config-dir",
            "--config",
            help="Путь до директории с конфигом",
            type=Path,
            dest="config_dir",
        )
        parser.add_argument(
            "--profile-id",
            "--profile",
            help="Профиль — подкаталог в config-dir (или env HH_PROFILE_ID)",
            dest="profile_id",
        )
        parser.add_argument(
            "-d",
            "--api-delay",
            "--delay",
            type=float,
            help="Задержка (сек) между запросами к API HH",
            dest="api_delay",
        )
        parser.add_argument(
            "--user-agent",
            help="User-Agent заголовок для запросов",
        )
        parser.add_argument(
            "--proxy-url",
            help="Прокси для запросов и авторизации",
        )
        parser.add_argument(
            "--version",
            action="version",
            version=self._get_version(),
        )

        subparsers = parser.add_subparsers(
            dest="command",
        )
        for kebab_name, op in ops:
            aliases = getattr(op, "__aliases__", [])
            op_parser = subparsers.add_parser(
                kebab_name,
                aliases=aliases,
                help=argparse.SUPPRESS,  # скрываем из главного списка — используем epilog
                description=op.__doc__,
                formatter_class=self.ArgumentFormatter,
            )
            if aliases:
                op_parser.epilog = f"Псевдонимы: {', '.join(aliases)}"
            op_parser.set_defaults(run=op.run)
            op.setup_parser(op_parser)
        parser.set_defaults(run=None)
        return parser

    def _get_version(self) -> str:
        try:
            from importlib.metadata import version

            return f"hh-applicant-tool {version(__package__ or 'hh-applicant-tool')}"
        except Exception:
            return "hh-applicant-tool (версия неизвестна)"

    def __init__(self, argv: Sequence[str] | None):
        self._parse_args(argv)

        # Создаем путь до конфига
        self.config_path.mkdir(
            parents=True,
            exist_ok=True,
        )

    def _get_proxies(self) -> dict[str, str]:
        proxy_url = self.args.proxy_url or self.config.get("proxy_url")

        if proxy_url:
            return {
                "http": proxy_url,
                "https": proxy_url,
            }

        proxies = {}
        http_env = getenv("HTTP_PROXY") or getenv("http_proxy")
        https_env = getenv("HTTPS_PROXY") or getenv("https_proxy") or http_env

        if http_env:
            proxies["http"] = http_env
        if https_env:
            proxies["https"] = https_env

        return proxies

    @cached_property
    def session(self) -> requests.Session:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        session = requests.Session()
        session.verify = False

        if proxies := self._get_proxies():
            logger.info("Use proxies for requests: %r", proxies)
            session.proxies = proxies

        session.cookies = HHOnlyCookieJar(str(self.cookies_file))
        if self.cookies_file.exists():
            session.cookies.load(ignore_discard=True, ignore_expires=True)

        session.headers.update({"User-Agent": DEFAULT_DESKTOP_USER_AGENT})

        return session

    @cached_property
    def config_path(self) -> Path:
        return (
            (
                self.args.config_dir
                or Path(getenv("CONFIG_DIR", DEFAULT_CONFIG_DIR))
            )
            / (self.args.profile_id or getenv("HH_PROFILE_ID", "."))
        ).resolve()

    @cached_property
    def config(self) -> utils.Config:
        return utils.Config(self.config_path / DEFAULT_CONFIG_FILENAME)

    @cached_property
    def log_file(self) -> Path:
        return self.config_path / DEFAULT_LOG_FILENAME

    @cached_property
    def cookies_file(self) -> Path:
        return self.config_path / DEFAULT_COOKIES_FILENAME

    @cached_property
    def db_path(self) -> Path:
        return self.config_path / DEFAULT_DATABASE_FILENAME

    @cached_property
    def db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        return conn

    @cached_property
    def storage(self) -> StorageFacade:
        return StorageFacade(self.db)

    @cached_property
    def api_client(self) -> api.client.ApiClient:
        args = self.args
        config = self.config
        token = config.get("token", {})
        return api.client.ApiClient(
            client_id=config.get("client_id"),
            client_secret=config.get("client_secret"),
            access_token=token.get("access_token"),
            refresh_token=token.get("refresh_token"),
            access_expires_at=token.get("access_expires_at"),
            delay=args.api_delay or config.get("api_delay"),
            user_agent=args.user_agent or config.get("user_agent"),
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

    def get_openai_chat(self, system_prompt: str) -> ai.ChatOpenAI:
        c = self.config.get("openai", {})
        if not (token := c.get("token")):
            raise ValueError("Токен для OpenAI не задан")
        return ai.ChatOpenAI(
            token=token,
            model=c.get("model"),
            temperature=c.get("temperature", 0.7),
            max_completion_tokens=c.get("max_completion_tokens", 1000),
            system_prompt=system_prompt,
            completion_endpoint=c.get("completion_endpoint"),
            session=self.session,
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

    def run(self) -> None | int:
        verbosity_level = max(
            logging.DEBUG,
            logging.WARNING - self.args.verbosity * 10,
        )

        setup_logger(logger, verbosity_level, self.log_file)

        logger.debug("Путь до профиля: %s", self.config_path)

        utils.setup_terminal()

        try:
            if self.args.run:
                try:
                    return self.args.run(self)
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
            from .utils.ui import print_banner_from_tool
            print_banner_from_tool(self)
            self._parser.print_help(file=sys.stderr)
            return 2
        finally:
            try:
                self._check_system()
            except Exception:
                pass
                # raise

    def _parse_args(self, argv) -> None:
        self._parser = self._create_parser()
        self.args = self._parser.parse_args(argv, namespace=BaseNamespace())


def main(argv: Sequence[str] | None = None) -> None | int:
    return HHApplicantTool(argv).run()
