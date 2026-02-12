from __future__ import annotations

import argparse
import logging
import os
import random
import sqlite3
import string
import sys
import time
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

from . import ai, api, datatypes, utils
from .storage import StorageFacade
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

        if self.cookies_file.exists():
            jar = MozillaCookieJar(str(self.cookies_file))
            jar.load(ignore_discard=True, ignore_expires=True)
            session.cookies = jar

        session.headers.update({"User-Agent": DEFAULT_DESKTOP_USER_AGENT})

        return session

    @property
    def is_logged_in(self) -> bool:
        """Проверяет авторизован ли пользователь через сайт."""
        return (
            self.session.get("https://hh.ru/applicant/settings").status_code
            == 200
        )

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
            client_secret=config.get("client_id"),
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
        return self.api_client.get("/resumes/mine")["items"]

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

    def _get_vacancy_tests(
        self, response_url: str
    ) -> tuple[datatypes.VacancyTestsData, str]:
        r = self.session.get(response_url)
        content = r.text
        tests = utils.json.loads(
            content.split(',"vacancyTests":')[1].split(',"counters":')[0],
            strict=False,
        )
        xsrf_token = content.split('"xsrfToken":"')[1].split('"')[0]
        return tests, xsrf_token

    def solve_vacancy_test(
        self,
        vacancy_id: str | int,
        resume_hash: str,
        letter: str = "",
    ) -> dict[str, Any]:
        """Загружает тест, ждет паузу и отправляет отклик."""
        response_url = f"https://hh.ru/applicant/vacancy_response?vacancyId={vacancy_id}&startedWithQuestion=false&hhtmFrom=vacancy"

        try:
            # Загружаем данные теста и токен
            tests, xsrf_token = self._get_vacancy_tests(response_url)
            test_data = tests[str(vacancy_id)]
        except IndexError:
            return {"error": "tests not found"}

        logger.debug(f"{test_data = }")

        payload: dict[str, Any] = {
            "_xsrf": xsrf_token,
            "uidPk": test_data["uidPk"],
            "guid": test_data["guid"],
            "startTime": test_data["startTime"],
            "testRequired": test_data["required"],
            "vacancy_id": vacancy_id,
            "resume_hash": resume_hash,
            "ignore_postponed": "true",
            "incomplete": "false",
            "mark_applicant_visible_in_vacancy_country": "false",
            "country_ids": "[]",
            "lux": "true",
            "withoutTest": "no",
            "letter": letter,
        }

        for task in test_data["tasks"]:
            field_name = f"task_{task['id']}"
            solutions = task.get("candidateSolutions", [])

            if solutions:
                payload[field_name] = random.choice(solutions)["id"]
            else:
                # Рандомные эмоджи
                # payload[f"{field_name}_text"] = "".join(
                #     chr(random.randint(0x1F300, 0x1F64F))
                #     for _ in range(random.randint(3, 15))
                # )
                payload[f"{field_name}_text"] = random.choice(
                    string.ascii_lowercase + string.digits
                ) * random.randint(5, 35)

        logger.debug(f"{payload = }")

        # Ожидание перед отправкой (float)
        time.sleep(random.uniform(2.0, 3.0))

        response = self.session.post(
            "https://hh.ru/applicant/vacancy_response/popup",
            data=payload,
            headers={
                "Referer": response_url,
                # x-gib-fgsscgib-w-hh и x-gib-gsscgib-w-hh вроде в куках
                # передаются и не нужны
                "X-Hhtmfrom": "vacancy",
                "X-Hhtmsource": "vacancy_response",
                "X-Requested-With": "XMLHttpRequest",
                "X-Xsrftoken": xsrf_token,
            },
        )

        logger.debug(
            "%s %s %d",
            response.request.method,
            response.url,
            response.status_code,
        )

        data = response.json()
        # logger.debug(data)

        return data

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
        if not self.session.cookies:
            return

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
