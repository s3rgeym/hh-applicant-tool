from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import TYPE_CHECKING

from ..api import ApiError
from ..main import BaseOperation
from ..main import Namespace as BaseNamespace

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    method: str
    endpoint: str
    params: list[str]


class Operation(BaseOperation):
    """Вызвать произвольный метод API <https://github.com/hhru/api>."""

    __aliases__ = ("api",)

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("endpoint", help="Путь до эндпоинта API")
        parser.add_argument(
            "param",
            nargs="*",
            help="Параметры указываются в виде PARAM=VALUE",
            default=[],
        )
        parser.add_argument(
            "-m", "--method", "--meth", "-X", default="GET", help="HTTP Метод"
        )

    def run(self, applicant_tool: HHApplicantTool) -> None:
        args = applicant_tool.args
        api_client = applicant_tool.api_client
        params = dict(x.split("=", 1) for x in args.param)
        try:
            result = api_client.request(args.method, args.endpoint, params=params)
            print(json.dumps(result, ensure_ascii=False))
        except ApiError as ex:
            json.dump(ex.data, sys.stderr, ensure_ascii=False)
            return 1
