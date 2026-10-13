from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import TYPE_CHECKING, Any

from ..api import ApiError
from ..tool import BaseNamespace, BaseOperation
from ..utils import json as jsonutils

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


logger = logging.getLogger("hh-applicant-tool")


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
        parser.add_argument(
            "--json",
            "-j",
            default=False,
            help="Принудительно отправить запрос телом в JSON и content-type application/json",
            action="store_true",
        )

    def _build_payload(
        self, params: list[str]
    ) -> tuple[dict[str, Any] | None, bool]:
        if not params:
            return None, False

        as_json = False
        payload = None

        if params[0].lstrip().startswith("{") and params[0].rstrip().endswith(
            "}"
        ):
            if len(params) > 1:
                raise ValueError(
                    "JSON должен быть единственным аргументом после endpoint!"
                )
            as_json = True
            payload = json.loads(params[0])
        elif self._args:
            as_json = True
            payload = {}
            for param in params:
                name, _, value = param.partition("=")
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
                payload[name] = value
        else:
            payload = {}
            for param in params:
                # API принимает параметры с одинаковым именем
                # Так сделано для фильтров вместо передачи
                # чего-то чз запятую
                key, _, value = param.partition("=")
                payload.setdefault(key, []).append(value)

        return payload, as_json

    def run(self, tool: HHApplicantTool, args: Namespace) -> None:
        self._args = args
        api_client = tool.api_client

        methods = {"GET", "POST", "PUT", "PATCH", "DELETE"}

        if args.arg[0].upper() in methods:
            method, endpoint, *params = args.arg
        else:
            method = "GET"
            endpoint, *params = args.arg

        payload, as_json = self._build_payload(params)
        logger.debug("%r %s", payload, as_json)
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
