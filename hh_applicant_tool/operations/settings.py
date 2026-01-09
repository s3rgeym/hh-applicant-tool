from __future__ import annotations

import argparse
import json
import logging
from typing import TYPE_CHECKING

from prettytable import PrettyTable

from ..main import BaseNamespace, BaseOperation
from ..utils import json_utils

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    key: str | None
    value: str | None
    delete: bool


def parse_value(v):
    try:
        return json_utils.loads(v)
    except json.JSONDecodeError:
        return v


class Operation(BaseOperation):
    """Просмотр и управление настройками"""

    __aliases__: list[str] = ["setting"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-d",
            "--delete",
            action="store_true",
            help="Удалить настройку по ключу",
        )
        parser.add_argument("key", nargs="?", help="Ключ настройки")
        parser.add_argument(
            "value", nargs="?", type=parse_value, help="Значение настройки"
        )

    def run(self, applicant_tool: HHApplicantTool) -> None:
        args: Namespace = applicant_tool.args
        storage = applicant_tool.storage

        if args.delete and args.key:
            # Delete value
            storage.settings.delete_value(args.key)
            print(f"🗑️ Настройка '{args.key}' удалена")
        elif args.key and args.value:
            storage.settings.set_value(args.key, args.value)
            print(f"✅ Установлено значение для '{args.key}'")
        elif args.key:
            # Get value
            value = storage.settings.get_setting(args.key)
            if value is not None:
                print(value)
            else:
                print(f"⚠️ Настройка '{args.key}' не найдена")
        else:
            # List all settings
            settings = storage.settings.find()
            t = PrettyTable(field_names=["Ключ", "Значение"], align="l")
            for setting in settings:
                if setting.key.startswith("_"):
                    continue
                t.add_row([setting.key, setting.value])
            print(t)
