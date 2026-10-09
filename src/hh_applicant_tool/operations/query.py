from __future__ import annotations

import argparse
import csv
import logging
import pathlib
import sqlite3
import sys
from typing import TYPE_CHECKING

from ..tool import BaseNamespace, BaseOperation
from ..utils.table import print_table

if TYPE_CHECKING:
    from ..tool import HHApplicantTool

try:
    import readline

    readline.parse_and_bind("tab: complete")
except ImportError:
    readline = None

MAX_RESULTS = 10
MAX_CELL_WIDTH = 60


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


def _cell(value: object) -> str:
    """Приводит значение ячейки к строке для вывода в таблицу."""
    if value is None:
        return "NULL"
    text = str(value).replace("\n", " ")
    if len(text) > MAX_CELL_WIDTH:
        text = text[: MAX_CELL_WIDTH - 1] + "…"
    return text


class Operation(BaseOperation):
    """Выполняет SQL-запрос. Поддерживает вывод в консоль или CSV файл."""

    __aliases__: list[str] = ["sql", "db"]

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

    def run(self, tool: HHApplicantTool, args: Namespace) -> None | int:
        def write_csv(columns: list[str], rows: list[tuple]) -> None:
            if args.output:
                with args.output.open("w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(columns)
                    writer.writerows(rows)
                print(f"✅  Exported to {args.output}")
            else:
                writer = csv.writer(sys.stdout)
                writer.writerow(columns)
                writer.writerows(rows)

        def execute(sql_query: str) -> int | None:
            sql_query = sql_query.strip()
            if not sql_query:
                return None
            try:
                cursor = tool.db.cursor()
                cursor.execute(sql_query)

                if cursor.description:
                    columns = [d[0] for d in cursor.description]

                    if args.csv or args.output:
                        write_csv(columns, cursor.fetchall())
                        return None

                    rows = cursor.fetchmany(MAX_RESULTS + 1)
                    if not rows:
                        print("No results found.")
                        return None

                    print_table(
                        columns,
                        [
                            tuple(_cell(v) for v in row)
                            for row in rows[:MAX_RESULTS]
                        ],
                    )

                    if len(rows) > MAX_RESULTS:
                        print(
                            f"⚠️  Warning: Showing only first {MAX_RESULTS} results."
                        )
                else:
                    tool.db.commit()

                    if cursor.rowcount > 0:
                        print(f"Rows affected: {cursor.rowcount}")

            except sqlite3.Error as ex:
                print(f"❌  SQL Error: {ex}", file=sys.stderr)
                return 1
            except OSError as ex:
                print(f"❌  File Error: {ex}", file=sys.stderr)
                return 1
            return None

        if initial_sql := args.sql:
            return execute(initial_sql)

        if not sys.stdin.isatty():
            return execute(sys.stdin.read())

        print("SQL Console (q or ^D to exit)")
        try:
            while True:
                try:
                    user_input = input("query> ").strip()
                    if user_input.lower() in ("exit", "quit", "q"):
                        break
                    execute(user_input)
                    print()
                except KeyboardInterrupt:
                    print("^C")
                    continue
        except EOFError:
            print()
        return None
