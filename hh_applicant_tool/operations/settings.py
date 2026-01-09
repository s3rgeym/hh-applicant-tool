from __future__ import annotations

import argparse
import json
import logging
from typing import TYPE_CHECKING

from prettytable import PrettyTable

from ..main import BaseNamespace, BaseOperation
from ..utils import jsonutil

if TYPE_CHECKING:
    from ..main import HHApplicantTool

_MISSING = object()

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    key: str | None
    value: str | None
    delete: bool


def parse_value(v):
    try:
        return jsonutil.loads(v)
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
        parser.add_argument(
            "key", nargs="?", help="Ключ настройки", default=_MISSING
        )
        parser.add_argument(
            "value",
            nargs="?",
            type=parse_value,
            help="Значение настройки",
            default=_MISSING,
        )

    def run(self, applicant_tool: HHApplicantTool) -> None:
        args: Namespace = applicant_tool.args
        settings = applicant_tool.storage.settings

        if args.delete:
            if args.key is not _MISSING:
                # Delete value
                settings.delete_value(args.key)
                print(f"🗑️ Настройка '{args.key}' удалена")
            else:
                settings.clear()
        elif args.key is not _MISSING and args.value is not _MISSING:
            settings.set_value(args.key, args.value)
            print(f"✅ Установлено значение для '{args.key}'")
        elif args.key is not _MISSING:
            # Get value
            value = settings.get_value(args.key)
            if value is not None:
                # print(type(value).__name__, value)
                print(value)
            else:
                print(f"⚠️ Настройка '{args.key}' не найдена")
        else:
            # List all settings
            settings = settings.find()
            t = PrettyTable(field_names=["Ключ", "Тип", "Значение"], align="l")
            for setting in settings:
                if setting.key.startswith("_"):
                    continue
                t.add_row(
                    [
                        setting.key,
                        type(setting.value).__name__,
                        setting.value,
                    ]
                )
            print(t)
