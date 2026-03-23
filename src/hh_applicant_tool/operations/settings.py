from __future__ import annotations

import argparse
import json
import logging
from typing import TYPE_CHECKING

from .. import utils
from ..main import BaseNamespace, BaseOperation
from ..utils.ui import console, info, make_table, ok, warn

if TYPE_CHECKING:
    from ..main import HHApplicantTool


MISSING = type("Missing", (), {"__str__": lambda self: "Не установлено"})()


logger = logging.getLogger(__package__)


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

    __aliases__: list[str] = ["setting"]
    __category__: str = "Конфигурация"

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "-d",
            "--delete",
            action="store_true",
            help="Удалить настройку по ключу либо удалить все насйтроки, если ключ не передан",
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

    def run(self, tool: HHApplicantTool) -> None:
        args: Namespace = tool.args
        settings = tool.storage.settings

        if args.delete:
            if args.key is not MISSING:
                settings.delete_value(args.key)
                ok(f"Настройка [bold]{args.key}[/bold] удалена")
            else:
                settings.clear()
                ok("Все настройки очищены")
        elif args.key is not MISSING and args.value is not MISSING:
            settings.set_value(args.key, args.value)
            ok(f"Установлено [bold]{args.key}[/bold] = [hh.accent]{args.value}[/]")
        elif args.key is not MISSING:
            value = settings.get_value(args.key, MISSING)
            if value is not MISSING:
                console.print(value)
            else:
                warn(f"Настройка [bold]{args.key}[/bold] не найдена")
        else:
            all_settings = settings.find()
            t = make_table("Ключ", "Тип", "Значение", title="Настройки")
            for setting in all_settings:
                if setting.key.startswith("_"):
                    continue
                t.add_row(
                    f"[bold]{setting.key}[/bold]",
                    f"[hh.muted]{type(setting.value).__name__}[/]",
                    str(setting.value),
                )
            console.print(t)
