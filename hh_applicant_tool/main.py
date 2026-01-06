from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from functools import cached_property
from importlib import import_module
from logging.handlers import RotatingFileHandler
from os import getenv
from pathlib import Path
from pkgutil import iter_modules
from typing import Any, Sequence

from .api import ApiClient
from .constants import ANDROID_CLIENT_ID, ANDROID_CLIENT_SECRET
from .log import ColorHandler, RedactingFilter
from .utils import Config, android_user_agent, fix_windows_color_output, get_config_path

DEFAULT_CONFIG_DIR = get_config_path() / (__package__ or "").replace("_", "-")
DEFAULT_CONFIG_FILENAME = "config.json"
DEFAULT_LOG_FILENAME = "log.txt"
DEFAULT_DATABASE_FILENAME = "data"
DEFAULT_PROFILE_ID = "."

logger = logging.getLogger(__package__)


class BaseOperation:
    def setup_parser(self, parser: argparse.ArgumentParser) -> None: ...

    def run(
        self,
        applicant_tool: HHApplicantTool,
    ) -> None | int:
        raise NotImplementedError()


OPERATIONS = "operations"


DATABASE_SCHEMA = """\
CREATE TABLE IF NOT EXISTS vacancies (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT NOT NULL,

    employer_id           INTEGER,
    employer_name         TEXT,

    area_id               INTEGER,
    area_name             TEXT,

    workplace_city        TEXT,
    workplace_lat         REAL,
    workplace_lng         REAL,
    workplace_raw         TEXT,

    salary_from           INTEGER,
    salary_to             INTEGER,
    salary_currency       TEXT,
    salary_gross          BOOLEAN,
    salary_mode_id        TEXT,
    salary_mode_name      TEXT,

    experience_id         TEXT,
    experience_name       TEXT,

    schedule_id           TEXT,
    schedule_name         TEXT,

    employment_id         TEXT,
    employment_name       TEXT,

    work_format_id        TEXT,
    work_format_name      TEXT,

    working_hours_id      TEXT,
    working_hours_name    TEXT,

    working_days_id       TEXT,
    working_days_name     TEXT,

    published_at          TEXT,
    created_at            TEXT,
    initial_created_at    TEXT,

    archived              BOOLEAN,
    approved              BOOLEAN,

    url                   TEXT,

    raw_json              TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS negotiations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    vacancy_id       INTEGER NOT NULL,
    resume_id        TEXT NOT NULL,
    message          TEXT,
    applied_at       TEXT DEFAULT (DATETIME('now', 'localtime')),
    status           TEXT DEFAULT 'response',
    FOREIGN KEY (vacancy_id) REFERENCES vacancies (id)
);
"""


class Namespace(argparse.Namespace):
    profile_id: str
    config_dir: Path
    verbosity: int
    delay: float
    user_agent: str
    proxy_url: str
    disable_telemetry: bool


class HHApplicantTool:
    """Утилита для автоматизации действий соискателя на сайте hh.ru.

    Исходники и предложения: <https://github.com/s3rgeym/hh-applicant-tool>

    Группа поддержки: <https://t.me/applicant_tool>
    """

    class ArgumentFormatter(
        argparse.ArgumentDefaultsHelpFormatter,
        argparse.RawDescriptionHelpFormatter,
    ):
        pass

    def create_parser(self) -> argparse.ArgumentParser:
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
            help="Используемый профиль — поддиректория в --config-dir",
            default=DEFAULT_PROFILE_ID,
        )
        parser.add_argument(
            "-d",
            "--delay",
            type=float,
            default=0.334,
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
            mod = import_module(f"{__package__}.{OPERATIONS}.{module_name}")
            op: BaseOperation = mod.Operation()
            # 1. Разбиваем имя модуля на части
            words = module_name.split("_")

            # 2. Формируем варианты имен
            kebab_name = "-".join(words)  # call-api
            aliases = []

            if kebab_name != module_name:
                # camelCase: первое слово маленькими, остальные с большой
                aliases.append(words[0] + "".join(word.title() for word in words[1:]))

                # flatcase: всё слитно и в нижнем регистре
                aliases.append("".join(words))

            op_parser = subparsers.add_parser(
                kebab_name,
                # Добавляем остальные варианты в псевдонимы
                aliases=aliases,
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

    @property
    def config_path(self) -> Path:
        return (self.args.config_dir / self.args.profile_id).resolve()

    @cached_property
    def config(self) -> Config:
        return Config(self.config_path / DEFAULT_CONFIG_FILENAME)

    @cached_property
    def log_file(self) -> Path:
        return self.config_path / DEFAULT_LOG_FILENAME

    @cached_property
    def database(self) -> sqlite3.Connection:
        db_path = self.config_path / DEFAULT_DATABASE_FILENAME
        conn = sqlite3.connect(db_path)

        # Инициализация именно вашей схемы
        self._init_db(conn)

        return conn

    def save_negotiation(self, vacancy_id: int, resume_id: str, message: str) -> None:
        """Фиксирует факт успешного отклика в базе."""
        sql = """
        INSERT INTO negotiations (vacancy_id, resume_id, message)
        VALUES (?, ?, ?)
        """
        self.databas.execute(sql, (vacancy_id, resume_id, message))
        self.databas.commit()

    def save_vacancy(self, v: dict[str, Any]) -> None:
        # Вложенные объекты
        emp = v.get("employer") or {}
        area = v.get("area") or {}
        addr = v.get("address") or {}
        sal = v.get("salary") or {}
        sal_range = v.get("salary_range") or {}
        sal_mode = sal_range.get("mode") or {}
        exp = v.get("experience") or {}
        sched = v.get("schedule") or {}
        empl = v.get("employment") or {}

        # Массивы: берем первый элемент для быстрой фильтрации в БД
        w_format = v.get("work_format", [{}])[0] if v.get("work_format") else {}
        w_hours = v.get("working_hours", [{}])[0] if v.get("working_hours") else {}
        w_days = (
            v.get("work_schedule_by_days", [{}])[0]
            if v.get("work_schedule_by_days")
            else {}
        )

        sql = """
        INSERT OR REPLACE INTO vacancies (
            id, name, employer_id, employer_name, area_id, area_name,
            workplace_city, workplace_lat, workplace_lng, workplace_raw,
            salary_from, salary_to, salary_currency, salary_gross,
            salary_mode_id, salary_mode_name, experience_id, experience_name,
            schedule_id, schedule_name, employment_id, employment_name,
            work_format_id, work_format_name, working_hours_id, working_hours_name,
            working_days_id, working_days_name, published_at, created_at,
            initial_created_at, archived, approved, url, raw_json
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """

        params = (
            v.get("id"),
            v.get("name"),
            emp.get("id"),
            emp.get("name"),
            area.get("id"),
            area.get("name"),
            addr.get("city"),
            addr.get("lat"),
            addr.get("lng"),
            addr.get("raw"),
            sal.get("from"),
            sal.get("to"),
            sal.get("currency"),
            sal.get("gross"),
            sal_mode.get("id"),
            sal_mode.get("name"),
            exp.get("id"),
            exp.get("name"),
            sched.get("id"),
            sched.get("name"),
            empl.get("id"),
            empl.get("name"),
            w_format.get("id"),
            w_format.get("name"),
            w_hours.get("id"),
            w_hours.get("name"),
            w_days.get("id"),
            w_days.get("name"),
            v.get("published_at"),
            v.get("created_at"),
            v.get("initial_created_at"),
            v.get("archived"),
            v.get("approved"),
            v.get("alternate_url"),
            json.dumps(v, ensure_ascii=False),
        )

        self.database.execute(sql, params)
        self.database.commit()

    def _init_db(self, conn: sqlite3.Connection) -> None:
        """Создает таблицу vacancies в строгом соответствии с заданной схемой."""
        conn.executescript(DATABASE_SCHEMA)
        conn.commit()
        logger.debug("Database initialized with the provided schema.")

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
            user_agent=config["user_agent"] or android_user_agent(),
            proxies=self._get_proxies(),
        )
        return api

    def get_me(self) -> dict:
        return self.api_client.get("/me")

    def get_resumes(self) -> dict:
        return self.api_client.get("/resumes/mine")

    def first_resume_id(self):
        resumes = self.api_client.get("/resumes/mine")
        return resumes["items"][0]["id"]

    def _setup_logger(self) -> None:
        args = self.args

        # В лог-файл пишем все!
        logger.setLevel(logging.DEBUG)

        # В консоль стараемся не мусорить
        log_level = max(logging.DEBUG, logging.WARNING - args.verbosity * 10)
        color_handler = ColorHandler()
        # [C] Critical Error Occurred
        color_handler.setFormatter(logging.Formatter("[%(levelname).1s] %(message)s"))
        color_handler.setLevel(log_level)

        # Логи
        file_handler = RotatingFileHandler(
            self.log_file,
            maxBytes=5 * 1 << 20,
            # backupCount=1,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        file_handler.setLevel(logging.DEBUG)

        redactor = RedactingFilter(
            [
                r"\bUSER[A-Z0-9]{60}\b",
                r"\b[a-fA-F0-9]{32}\b",  # request_id, возвращаемый сервером содержит хеш от айпи  # noqa: E501
                ANDROID_CLIENT_SECRET,
            ]
        )

        for h in [color_handler, file_handler]:
            h.addFilter(redactor)
            logger.addHandler(h)

    def run(self, argv: Sequence[str] | None) -> None | int:
        parser = self.create_parser()
        self.args = parser.parse_args(argv, namespace=Namespace())

        if sys.platform == "win32":
            fix_windows_color_output()

        # Создаем путь до конфига
        self.config_path.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._setup_logger()

        if self.args.run:
            try:
                res = self.args.run(self)

                if self.api_client.access_token != self.config.get("token", {}).get(
                    "access_token"
                ):
                    logger.info("access token updated!")
                    self.config.save(token=self.api_client.get_access_token())

                return res
            except KeyboardInterrupt:
                logger.warning("Interrupted by user")
                return 1
            except Exception as e:
                logger.exception(e, exc_info=True)
                return 1
        parser.print_help(file=sys.stderr)
        return 2


def main(argv: Sequence[str] | None = None) -> None | int:
    return HHApplicantTool().run(argv)
