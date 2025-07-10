# Этот модуль можно использовать как образец для других
import argparse
import json
import logging
import sys

from ..api import ApiClient, ApiError
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    method: str
    endpoint: str
    params: list[str]
    pretty_print: bool


class Operation(BaseOperation):
    """Вызвать произвольный метод API <https://github.com/hhru/api>."""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("endpoint", help="Путь до эндпоинта API")
        parser.add_argument(
            "param",
            nargs="*",
            help="Параметры указываются в виде PARAM=VALUE",
            default=[],
        )
        parser.add_argument(
            "-m", "--method", "--meth", default="GET", help="HTTP Метод"
        )

    def run(self, args: Namespace, api_client: ApiClient, *_) -> None:
        params = dict(x.split("=", 1) for x in args.param)
        try:
            result = api_client.request(args.method, args.endpoint, params=params)
            print(json.dumps(result, ensure_ascii=False))
        except ApiError as ex:
            json.dump(ex.data, sys.stderr, ensure_ascii=False)
            return 1
