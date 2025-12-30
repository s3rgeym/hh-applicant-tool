from __future__ import annotations

import argparse
import logging
import sys
from importlib import import_module
from os import getenv
from pathlib import Path
from pkgutil import iter_modules
from typing import Literal, Sequence

from .api import ApiClient
from .color_log import ColorHandler
from .constants import ANDROID_CLIENT_ID, ANDROID_CLIENT_SECRET
from .telemetry_client import TelemetryClient
from .utils import Config, android_user_agent, get_config_path

DEFAULT_CONFIG_PATH = (
    get_config_path() / (__package__ or "").replace("_", "-") / "config.json"
)

logger = logging.getLogger(__package__)


class BaseOperation:
    def setup_parser(self, parser: argparse.ArgumentParser) -> None: ...

    def run(self, args: argparse.Namespace, api_client: ApiClient, telemetry_client: TelemetryClient) -> None | int:
        raise NotImplementedError()


OPERATIONS = "operations"


class Namespace(argparse.Namespace):
    config: Config
    verbosity: int
    delay: float
    user_agent: str
    proxy_url: str
    disable_telemetry: bool


def get_proxies(args: Namespace) -> dict[str, str]:
    proxy_url = args.proxy_url or args.config.get("proxy_url")
    
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


def get_api_client(args: Namespace) -> ApiClient:
    config = args.config
    token = config.get("token", {})
    api = ApiClient(
        client_id=config.get("client_id", ANDROID_CLIENT_ID),
        client_secret=config.get("client_id", ANDROID_CLIENT_SECRET),
        access_token=token.get("access_token"),
        refresh_token=token.get("refresh_token"),
        access_expires_at=token.get("access_expires_at"),
        delay=args.delay,
        user_agent=config["user_agent"] or android_user_agent(),
        proxies=get_proxies(args),
    )
    return api


class HHApplicantTool:
    """Утилита для автоматизации действий соискателя на сайте hh.ru.

    Исходники и предложения: <https://github.com/s3rgeym/hh-applicant-tool>

    Группа поддержки: <https://t.me/hh_applicant_tool>
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
            # 1. Разбиваем имя модуля на части
            words = module_name.split("_")

            # 2. Формируем варианты имен
            kebab_name = "-".join(words)  # call-api
            
            # camelCase: первое слово маленькими, остальные с большой
            camel_case_name = words[0] + "".join(word.title() for word in words[1:])
            
            # flatcase: всё слитно и в нижнем регистре
            flat_name = "".join(words)  # callapi

            op_parser = subparsers.add_parser(
                kebab_name,
                # Добавляем остальные варианты в псевдонимы
                aliases=[camel_case_name, flat_name],
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
                logger.exception(e, exc_info=log_level <= logging.DEBUG)
                return 1
        parser.print_help(file=sys.stderr)
        return 2


def main(argv: Sequence[str] | None = None) -> None | int:
    return HHApplicantTool().run(argv)
