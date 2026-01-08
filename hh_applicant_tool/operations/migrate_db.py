from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from typing import TYPE_CHECKING

from ..main import BaseNamespace, BaseOperation
from ..storage import apply_migration, list_migrations

if TYPE_CHECKING:
    from ..main import HHApplicantTool

SUCKASS = "✅ Success!"

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Выполняет миграцию БД. Если первым аргументом имя миграции не передано, выведет их список."""  # noqa: E501

    __aliases__: list[str] = ["migrate"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("name", nargs="?", help="Имя миграции")

    def run(self, applicant_tool: HHApplicantTool) -> None:
        def apply(name: str) -> None:
            apply_migration(applicant_tool.db, name)
            print(SUCKASS)

        try:
            if a := applicant_tool.args.name:
                return apply(a)
            if not (migrations := list_migrations()):
                return
            if not sys.stdout.isatty():
                print(*list_migrations(), sep=os.sep)
                return
            print("List of migrations:")
            print()
            for n, migration in enumerate(migrations, 1):
                print(f"  [{n}]: {migration}")
            print()
            L = len(migrations)
            if n := int(
                input(
                    f"Choose migraion [1{f'-{L}' if L > 1 else ''}] (Keep empty to exit): "  # noqa: E501
                )
                or 0
            ):
                apply(migrations[n - 1])
        except sqlite3.OperationalError as ex:
            logger.exception(ex)
            logger.warning(
                f"Если ничего не помогает, то вы можете просто удалить базу, сделав бекап:\n\n"
                f"  $ mv {applicant_tool.db_path}{{,.bak}}"
            )
            return 1
