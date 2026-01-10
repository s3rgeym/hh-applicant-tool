from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from collections.abc import Sequence
from functools import cached_property
from importlib import import_module
from itertools import count
from logging.handlers import RotatingFileHandler
from os import getenv
from pathlib import Path
from pkgutil import iter_modules
from typing import Any, Iterable

import requests
import urllib3

from . import datatypes, utils
from .api import ApiClient
from .constants import ANDROID_CLIENT_ID, ANDROID_CLIENT_SECRET
from .storage import StorageFacade
from .utils.log import ColorHandler, RedactingFilter
from .utils.mixins import MegaTool

DEFAULT_CONFIG_DIR = utils.get_config_path() / (__package__ or "").replace(
    "_", "-"
)
DEFAULT_CONFIG_FILENAME = "config.json"
DEFAULT_LOG_FILENAME = "log.txt"
DEFAULT_DATABASE_FILENAME = "data"
DEFAULT_PROFILE_ID = "."

# 10MB
MAX_LOG_SIZE = 10 << 20

logger = logging.getLogger(__package__)


class BaseOperation:
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
    disable_telemetry: bool


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

    def _create_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description=self.__doc__,
            formatter_class=self.ArgumentFormatter,
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
            default=DEFAULT_CONFIG_DIR,
        )
        parser.add_argument(
            "--profile-id",
            "--profile",
            help="Используемый профиль — подкаталог в --config-dir",
            default=DEFAULT_PROFILE_ID,
        )
        parser.add_argument(
            "-d",
            "--delay",
            type=float,
            default=0.654,
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
                formatter_class=self.ArgumentFormatter,
            )
            op_parser.set_defaults(run=op.run)
            op.setup_parser(op_parser)
        parser.set_defaults(run=None)
        return parser

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

        session = requests.session()
        session.verify = False

        if proxies := self._get_proxies():
            logger.info("Use proxies: %r", proxies)
            session.proxies = proxies

        return session

    @property
    def config_path(self) -> Path:
        return (self.args.config_dir / self.args.profile_id).resolve()

    @cached_property
    def config(self) -> utils.Config:
        return utils.Config(self.config_path / DEFAULT_CONFIG_FILENAME)

    @cached_property
    def log_file(self) -> Path:
        return self.config_path / DEFAULT_LOG_FILENAME

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
    def api_client(self) -> ApiClient:
        args = self.args
        config = self.config
        token = config.get("token", {})
        api = ApiClient(
            client_id=config.get("client_id", ANDROID_CLIENT_ID),
            client_secret=config.get("client_id", ANDROID_CLIENT_SECRET),
            access_token=token.get("access_token"),
            refresh_token=token.get("refresh_token"),
            access_expires_at=token.get("access_expires_at"),
            delay=args.delay,
            user_agent=config["user_agent"] or utils.hh_android_useragent(),
            session=self.session,
        )
        return api

    def get_me(self) -> datatypes.User:
        return self.api_client.get("me")

    def get_resumes(self) -> datatypes.PaginatedItems[datatypes.Resume]:
        return self.api_client.get("/resumes/mine")

    def first_resume_id(self):
        resumes = self.api_client.get("/resumes/mine")
        assert len(resumes["items"]), "Empty resume list"
        return resumes["items"][0]["id"]

    def get_blacklisted(self) -> list[str]:
        rv = []
        for page in count():
            r: datatypes.PaginatedItems[datatypes.EmployerShort] = (
                self.api_client.get("/employers/blacklisted", page=page)
            )
            rv += [item["id"] for item in r["items"]]
            if page + 1 >= r["pages"]:
                break
        return rv

    def get_negotiations(
        self, status: str = "active"
    ) -> Iterable[datatypes.Negotiation]:
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

    def _setup_logger(self) -> None:
        args = self.args

        # В лог-файл пишем все!
        logger.setLevel(logging.DEBUG)

        # В консоль стараемся не мусорить
        log_level = max(logging.DEBUG, logging.WARNING - args.verbosity * 10)
        color_handler = ColorHandler()
        # [C] Critical Error Occurred
        color_handler.setFormatter(
            logging.Formatter("[%(levelname).1s] %(message)s")
        )
        color_handler.setLevel(log_level)

        # Логи
        file_handler = RotatingFileHandler(
            self.log_file,
            maxBytes=MAX_LOG_SIZE,
            # backupCount=1,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        file_handler.setLevel(logging.DEBUG)

        redactor = RedactingFilter(
            [
                r"\b[A-Z0-9]{64,}\b",
                r"\b[a-fA-F0-9]{32,}\b",  # request_id, resume_id
            ]
        )

        for h in [color_handler, file_handler]:
            h.addFilter(redactor)
            logger.addHandler(h)

    def run(self, argv: Sequence[str] | None) -> None | int:
        parser = self._create_parser()
        self.args = parser.parse_args(argv, namespace=BaseNamespace())

        if sys.platform == "win32":
            utils.setup_terminal()

        # Создаем путь до конфига
        self.config_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._setup_logger()

        try:
            if self.args.run:
                try:
                    res = self.args.run(self)

                    if self.api_client.access_token != self.config.get(
                        "token", {}
                    ).get("access_token"):
                        logger.info("Токен был обновлен.")
                        self.config.save(
                            token=self.api_client.get_access_token()
                        )

                    return res
                except KeyboardInterrupt:
                    logger.warning("Выполнение прервано пользователем!")
                    return 1
                except sqlite3.Error as ex:
                    logger.exception(ex)

                    script_name = sys.argv[0].split(os.sep)[-1]

                    logger.warning(
                        f"Возможно база данных повреждена, попробуйте выполнить команду:\n\n"  # noqa: E501
                        f"  {script_name} migrate-db"
                    )
                    return 1
                except Exception as e:
                    logger.exception(e)
                    return 1
            parser.print_help(file=sys.stderr)
            return 2
        finally:
            try:
                self.check_system()
            except Exception as ex:
                logger.exception(ex)


def main(argv: Sequence[str] | None = None) -> None | int:
    return HHApplicantTool().run(argv)
