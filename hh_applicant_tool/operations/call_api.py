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
        parser.add_argument("endpoint")
        parser.add_argument(
            "param",
            nargs="*",
            help="PARAM=VALUE",
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
        try:
            result = api.request(args.method, args.endpoint, params=params)
            print(json.dumps(result, ensure_ascii=True))
        except ApiError as ex:
            json.dump(ex.data, sys.stderr, ensure_ascii=True)
            return 1
