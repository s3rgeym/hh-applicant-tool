from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from ..api import ApiError
from ..main import BaseNamespace, BaseOperation
from ..utils import json
from ..utils.ui import console, err

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    method: str
    endpoint: str
    params: list[str]
    data: Any


class Operation(BaseOperation):
    """Вызвать произвольный метод API <https://github.com/hhru/api>."""

    __aliases__ = ("api",)
    __category__: str = "Утилиты"

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
        # Добавляем аргумент для JSON тела
        parser.add_argument("-d", "--data", help="JSON строка тела запроса")

    def run(self, tool: HHApplicantTool) -> None:
        args = tool.args
        api_client = tool.api_client

        # Парсим JSON, если он передан
        as_json = False
        if args.data:
            try:
                params = json.loads(args.data)
                as_json = True
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in --data: {e}")
                return 1
        else:
            params = defaultdict(list)
            for param in args.param:
                key, value = param.split("=", 1)
                params[key].append(value)

            # Это лишнее, наверное
            params = dict(params)

        try:
            result = api_client.request(
                args.method,
                args.endpoint,
                params=params,
                as_json=as_json,
            )
            console.print_json(json.dumps(result))
        except ApiError as ex:
            logger.debug(ex)
            err(f"API Error: {ex}")
            console.print_json(json.dumps(ex.data))
            return 1
