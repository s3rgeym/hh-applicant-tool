from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from typing import TYPE_CHECKING

from ..main import BaseNamespace, BaseOperation
from ..storage import apply_migration, list_migrations
from ..utils.ui import console, err, info, ok

if TYPE_CHECKING:
    from ..main import HHApplicantTool

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Выполняет миграцию БД. Если первым аргументом имя миграции не передано, выведет их список."""  # noqa: E501

    __aliases__: list[str] = ["migrate"]
    __category__: str = "Утилиты"

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("name", nargs="?", help="Имя миграции")

    def run(self, tool: HHApplicantTool) -> None:
        def apply(name: str) -> None:
            info(f"Применяю миграцию: [bold]{name}[/bold]")
            apply_migration(tool.db, name)
            ok(f"Миграция применена: [bold]{name}[/bold]")

        try:
            if a := tool.args.name:
                return apply(a)
            if not (migrations := list_migrations()):
                ok("Миграций нет.")
                return
            if not sys.stdout.isatty():
                print(*migrations, sep=os.sep)
                return
            from ..utils.ui import make_table
            t = make_table("№", "Миграция", title="Доступные миграции")
            for n, migration in enumerate(migrations, 1):
                t.add_row(str(n), migration)
            console.print(t)
            console.print()
            L = len(migrations)
            choice = input(
                f"Выберите миграцию [1{f'-{L}' if L > 1 else ''}] (Enter для выхода): "
            ).strip()
            if choice and (n := int(choice or 0)):
                apply(migrations[n - 1])
        except sqlite3.OperationalError as ex:
            logger.exception(ex)
            err(
                f"Если ничего не помогает — удалите базу (сделав бекап):\n\n"
                f"  mv {tool.db_path}{{,.bak}}"
            )
            return 1
