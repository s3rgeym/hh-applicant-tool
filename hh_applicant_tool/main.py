from __future__ import annotations

import argparse
import logging
import sys
from abc import ABCMeta, abstractmethod
from importlib import import_module
from pathlib import Path
from pkgutil import iter_modules
from typing import Sequence, Literal
from .api import ApiClient
from .color_log import ColorHandler
from .utils import Config, get_config_path
from os import getenv

DEFAULT_CONFIG_PATH = (
    get_config_path() / __package__.replace("_", "-") / "config.json"
)

logger = logging.getLogger(__package__)


class BaseOperation(metaclass=ABCMeta):
    def setup_parser(self, parser: argparse.ArgumentParser) -> None: ...

    @abstractmethod
    def run(self, args: argparse.Namespace) -> None | int: ...


OPERATIONS = "operations"


class Namespace(argparse.Namespace):
    config: Config
    verbosity: int
    delay: float
    user_agent: str
    proxy_url: str


def get_proxies(args: Namespace) -> dict[Literal["http", "https"], str | None]:
    return {
        "http": args.config["proxy_url"] or getenv("HTTP_PROXY"),
        "https": args.config["proxy_url"] or getenv("HTTPS_PROXY"),
    }


def get_api(args: Namespace) -> ApiClient:
    token = args.config.get("token", {})
    api = ApiClient(
        access_token=token.get("access_token"),
        refresh_token=token.get("refresh_token"),
        delay=args.delay,
        user_agent=args.config["user_agent"],
        proxies=get_proxies(args),
    )
    return api


class HHApplicantTool:
    """Утилита для автоматизации действий соискателя на сайте hh.ru.

    Исходники и предложения: <https://github.com/s3rgeym/hh-applicant-tool>

    Группа поддержки: <https://t.me/+aSjr8qM_AP85ZDBi>
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
            "-c",
            "--config",
            help="Путь до файла конфигурации",
            type=Config,
            default=Config(DEFAULT_CONFIG_PATH),
        )
        parser.add_argument(
            "-v",
            "--verbosity",
            help="При использовании от одного и более раз увеличивает количество отладочной информации в выводе",
            action="count",
            default=0,
        )
        parser.add_argument(
            "-d",
            "--delay",
            type=float,
            default=0.334,
            help="Задержка между запросами к API HH",
        )
        parser.add_argument(
            "--user-agent", help="User-Agent для каждого запроса"
        )
        parser.add_argument(
            "--proxy-url", help="Прокси, используемый для запросов к API"
        )
        subparsers = parser.add_subparsers(help="commands")
        package_dir = Path(__file__).resolve().parent / OPERATIONS
        for _, module_name, _ in iter_modules([str(package_dir)]):
            mod = import_module(f"{__package__}.{OPERATIONS}.{module_name}")
            op: BaseOperation = mod.Operation()
            op_parser = subparsers.add_parser(
                module_name.replace("_", "-"),
                description=op.__doc__,
                formatter_class=self.ArgumentFormatter,
            )
            op_parser.set_defaults(run=op.run)
            op.setup_parser(op_parser)
        parser.set_defaults(run=None)
        return parser

    def run(self, argv: Sequence[str] | None) -> None | int:
        parser = self.create_parser()
        args = parser.parse_args(argv, namespace=Namespace())
        log_level = max(logging.DEBUG, logging.WARNING - args.verbosity * 10)
        logger.setLevel(log_level)
        handler = ColorHandler()
        # [C] Critical Error Occurred
        handler.setFormatter(logging.Formatter("[%(levelname).1s] %(message)s"))
        logger.addHandler(handler)
        if args.run:
            try:
                return args.run(args)
            except Exception as e:
                logger.exception(e)
                return 1
        parser.print_help(file=sys.stderr)
        return 2


def main(argv: Sequence[str] | None = None) -> None | int:
    return HHApplicantTool().run(argv)
