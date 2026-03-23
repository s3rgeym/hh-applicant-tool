from __future__ import annotations

import argparse
import csv
import logging
import pathlib
import sqlite3
import sys
from typing import TYPE_CHECKING

from ..main import BaseNamespace, BaseOperation
from ..utils.ui import console, err, info, make_table, ok, warn

if TYPE_CHECKING:
    from ..main import HHApplicantTool

try:
    import readline

    readline.parse_and_bind("tab: complete")
except ImportError:
    readline = None

MAX_RESULTS = 10


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Выполняет SQL-запрос. Поддерживает вывод в консоль или CSV файл."""

    __aliases__: list[str] = ["sql"]
    __category__: str = "Утилиты"

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("sql", nargs="?", help="SQL запрос")
        parser.add_argument(
            "--csv", action="store_true", help="Вывести результат в формате CSV"
        )
        parser.add_argument(
            "-o",
            "--output",
            type=pathlib.Path,
            help="Файл для сохранения",
        )

    def run(self, tool: HHApplicantTool) -> None:
        def execute(sql_query: str) -> None:
            sql_query = sql_query.strip()
            if not sql_query:
                return
            try:
                cursor = tool.db.cursor()
                cursor.execute(sql_query)

                if cursor.description:
                    columns = [d[0] for d in cursor.description]

                    if tool.args.csv or tool.args.output:
                        output = (
                            tool.args.output.open("w", encoding="utf-8")
                            if tool.args.output
                            else sys.stdout
                        )
                        writer = csv.writer(output)
                        writer.writerow(columns)
                        writer.writerows(cursor.fetchall())

                        if output is not sys.stdout:
                            ok(f"Экспортировано в {output.name}")
                        return

                    rows = cursor.fetchmany(MAX_RESULTS + 1)
                    if not rows:
                        info("Результатов не найдено.")
                        return

                    table = make_table(*columns)
                    for row in rows[:MAX_RESULTS]:
                        table.add_row(*[str(v) if v is not None else "[hh.muted]—[/]" for v in row])

                    console.print(table)

                    if len(rows) > MAX_RESULTS:
                        warn(f"Показаны первые {MAX_RESULTS} результатов.")
                else:
                    tool.db.commit()

                    if cursor.rowcount > 0:
                        info(f"Затронуто строк: [bold]{cursor.rowcount}[/bold]")

            except sqlite3.Error as ex:
                err(f"SQL Error: {ex}")
                return 1

        if initial_sql := tool.args.sql:
            return execute(initial_sql)

        if not sys.stdin.isatty():
            return execute(sys.stdin.read())

        info("SQL Console (q или ^D для выхода)")
        try:
            while True:
                try:
                    user_input = input("query> ").strip()
                    if user_input.lower() in (
                        "exit",
                        "quit",
                        "q",
                    ):
                        break
                    execute(user_input)
                    print()
                except KeyboardInterrupt:
                    print("^C")
                    continue
        except EOFError:
            print()
