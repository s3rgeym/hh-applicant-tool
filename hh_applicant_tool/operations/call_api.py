# Этот модуль можно использовать как образец для других
import argparse
import logging

from ..api import ApiClient
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace
from ..utils import dumps

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    method: str
    endpoint: str
    params: list[str]


class Operation(BaseOperation):
    """Вызвать произвольный метод API <https://github.com/hhru/api>."""

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("endpoint")
        parser.add_argument(
            "param",
            nargs="*",
            help="PARAM=VALUE. Значения можно оборачивать в кавычки.",
            default=[],
        )
        parser.add_argument(
            "-m", "--method", "--meth", default="GET", help="HTTP Метод"
        )

    def run(self, args: Namespace) -> None:
        assert args.config["token"]
        api = ApiClient(
            access_token=args.config["token"]["access_token"],
            user_agent=args.config["user_agent"],
        )
        params = dict(x.split("=", 1) for x in args.param)
        result = api.request(args.method, args.endpoint, params=params)
        print(dumps(result))
