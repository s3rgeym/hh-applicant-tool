from __future__ import annotations

import argparse
import logging
import sys
from importlib import import_module
from os import getenv
from pathlib import Path
from pkgutil import iter_modules
from typing import Literal, Sequence, Dict

from .api import ApiClient
from .color_log import ColorHandler
from .telemetry_client import TelemetryClient
from .utils import Config, get_config_path

DEFAULT_CONFIG_PATH = (
    get_config_path() / (__package__ or "").replace("_", "-") / "config.json"
)

logger = logging.getLogger(__package__)


class BaseOperation:
    def setup_parser(self, parser: argparse.ArgumentParser) -> None: ...

    def run(self, args: argparse.Namespace) -> None | int:
        raise NotImplementedError()


OPERATIONS = "operations"


class Namespace(argparse.Namespace):
    config: Config
    verbosity: int
    delay: float
    user_agent: str
    proxy_url: str
    disable_telemetry: bool


def get_proxies(args: Namespace) -> dict[Literal["http", "https"], str | None]:
    return {
        "http": args.config["proxy_url"] or getenv("HTTP_PROXY"),
        "https": args.config["proxy_url"] or getenv("HTTPS_PROXY"),
    }


def get_api_client(args: Namespace) -> ApiClient:
    token = args.config.get("token", {})
    api = ApiClient(
        access_token=token.get("access_token"),
        refresh_token=token.get("refresh_token"),
        access_expires_at=token.get("access_expires_at"),
        delay=args.delay,
        user_agent=args.config["user_agent"],
        proxies=get_proxies(args),
    )
    return api


class HHApplicantTool:
    """Утилита для автоматизации действий соискателя на сайте hh.ru.

    Исходники и предложения: <https://github.com/s3rgeym/hh-applicant-tool>

    Группа поддержки: <https://t.me/otzyvy_headhunter>
    """

    class ArgumentFormatter(
        argparse.ArgumentDefaultsHelpFormatter,
        argparse.RawDescriptionHelpFormatter,
    ):
        pass
    
    def api_init_client(self) -> ApiClient:
        return get_api_client(self.create_parser().parse_args(namespace=Namespace()))

    def api_init_operations(self) -> Dict[str, BaseOperation]:
        operations = dict()
        package_dir = Path(__file__).resolve().parent / OPERATIONS
        for _, module_name, _ in iter_modules([str(package_dir)]):
            mod = import_module(f"{__package__}.{OPERATIONS}.{module_name}")
            op: BaseOperation = mod.Operation()
            operations[module_name] = op
        
        return operations

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
        parser.add_argument("--user-agent", help="User-Agent для каждого запроса")
        parser.add_argument(
            "--proxy-url", help="Прокси, используемый для запросов к API"
        )
        parser.add_argument(
            "--disable-telemetry",
            default=False,
            action=argparse.BooleanOptionalAction,
            help="Отключить телеметрию",
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
                if not args.config["telemetry_client_id"]:
                    import uuid

                    args.config.save(telemetry_client_id=str(uuid.uuid4()))
                api_client = get_api_client(args)
                telemetry_client = TelemetryClient(
                    telemetry_client_id=args.config["telemetry_client_id"],
                    proxies=api_client.proxies.copy(),
                )
                # 0 or None = success
                res = args.run(args, api_client, telemetry_client)
                if (token := api_client.get_access_token()) != args.config["token"]:
                    args.config.save(token=token)
                return res
            except KeyboardInterrupt:
                logger.warning("Interrupted by user")
                return 1
            except Exception as e:
                logger.exception(e)
                return 1
        parser.print_help(file=sys.stderr)
        return 2


def main(argv: Sequence[str] | None = None) -> None | int:
    return HHApplicantTool().run(argv)
