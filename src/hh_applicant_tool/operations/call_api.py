from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import TYPE_CHECKING

from ..api import ApiError
from ..tool import BaseNamespace, BaseOperation
from ..utils import json as jsonutils

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    arguments: list[str]


class Operation(BaseOperation):
    """Вызвать произвольный метод API <https://github.com/hhru/api>."""

    __aliases__ = ("api",)

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "arg",
            nargs="+",
            help=(
                "Метод, путь до эндпоинта API и параметры."
                " Метод можно опустить, тогда будет использоваться GET."
                " Параметры можно передать в виде ключ='значение', при чем значения не нужно кодировать,"
                " либо в виде объекта JSON аргументом сразу после пути."
            ),
        )

    def run(self, tool: HHApplicantTool, args: Namespace) -> None:
        api_client = tool.api_client

        methods = {"GET", "POST", "PUT", "PATCH", "DELETE"}

        if args.arg[0].upper() in methods:
            method, endpoint, *params = args.arg
        else:
            method = "GET"
            endpoint, *params = args.arg

        payload = None
        as_json = False
        if len(params) > 0:
            if params[0].lstrip().startswith("{") and params[
                0
            ].rstrip().endswith("}"):
                try:
                    payload = json.loads(params[0])
                    as_json = True
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON: {e}")
                    return 1
                if len(params) > 1:
                    logger.warning(
                        "При JSON-запросе все аргументы после документа игнорируются!"
                    )
            else:
                payload = {}
                for param in params:
                    key, value = param.split("=", 1)
                    # В их API можно передать любое количество параметров с
                    # одинаковым именем. Так передаются айдишники и фильтры
                    # разные вместо объединения их через запятую как у
                    # нормальных людей
                    payload.setdefault(key, []).append(value)

        try:
            result = api_client.request(
                method,
                endpoint,
                params=payload,
                as_json=as_json,
            )
            print(jsonutils.dumps(result))
        except ApiError as ex:
            logger.debug(ex)
            jsonutils.dump(ex.data, sys.stderr)
            return 1
