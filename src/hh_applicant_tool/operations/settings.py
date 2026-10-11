from __future__ import annotations

import argparse
import json
import logging
from typing import TYPE_CHECKING

from .. import utils
from ..tool import BaseNamespace, BaseOperation
from ..utils.table import print_table

if TYPE_CHECKING:
    from ..tool import HHApplicantTool


MISSING = type("Missing", (), {"__str__": lambda self: "Не установлено"})()
MAX_VALUE_WIDTH = 80


logger = logging.getLogger(__name__.split(".")[0])


class Namespace(BaseNamespace):
    key: str | None
    value: str | None
    delete: bool


def parse_value(v):
    try:
        return utils.json.loads(v)
    except json.JSONDecodeError:
        return v


class Operation(BaseOperation):
    """Просмотр и управление настройками"""

    __aliases__: list[str] = ["setting", "set"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-d",
            "--delete",
            action="store_true",
            help="Удалить настройку по ключу либо удалить все настройки, если ключ не передан",
        )
        parser.add_argument(
            "key", nargs="?", help="Ключ настройки", default=MISSING
        )
        parser.add_argument(
            "value",
            nargs="?",
            type=parse_value,
            help="Значение настройки",
            default=MISSING,
        )

    def run(self, tool: HHApplicantTool, args: Namespace) -> None:
        settings = tool.storage.settings

        if args.delete:
            if args.key is not MISSING:
                # Delete value
                settings.delete_value(args.key)
                print(f"🗑️ Настройка '{args.key}' удалена")
            else:
                settings.clear()
        elif args.key is not MISSING and args.value is not MISSING:
            settings.set_value(args.key, args.value)
            print(f"✅ Установлено значение для '{args.key}'")
        elif args.key is not MISSING:
            # Get value
            value = settings.get_value(args.key, MISSING)
            if value is not MISSING:
                print(value)
            else:
                print(f"⚠️ Настройка '{args.key}' не найдена")
        else:
            # List all settings
            print_table(
                headers=["Ключ", "Тип", "Значение"],
                rows=[
                    (
                        s.key,
                        type(s.value).__name__,
                        "None" if s.value is None else s.value,
                    )
                    for s in settings.find()
                    if not s.key.startswith("_")
                ],
            )
