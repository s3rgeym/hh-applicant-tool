from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
import sys
from typing import TYPE_CHECKING

from prettytable import PrettyTable

from ..main import BaseNamespace, BaseOperation

if TYPE_CHECKING:
    from ..main import HHApplicantTool

try:
    import readline

    readline.parse_and_bind("tab: complete")
except ImportError:
    readline = None

logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Выполняет SQL-запрос. Поддерживает вывод в консоль или CSV файл."""

    __aliases__: list[str] = ["sql"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("sql", nargs="?", help="SQL запрос")
        parser.add_argument(
            "--csv", action="store_true", help="Вывести результат в формате CSV"
        )
        parser.add_argument(
            "-o",
            "--output",
            type=argparse.FileType("w", encoding="utf-8"),
            help="Файл для сохранения",
        )

    def run(self, applicant_tool: HHApplicantTool) -> None:
        def execute(sql_query: str) -> None:
            sql_query = sql_query.strip()
            if not sql_query:
                return
            try:
                cursor = applicant_tool.db.cursor()
                cursor.execute(sql_query)

                if cursor.description:
                    columns = [d[0] for d in cursor.description]

                    if applicant_tool.args.csv or applicant_tool.args.output:
                        # Если -o не задан, используем sys.stdout
                        output = applicant_tool.args.output or sys.stdout
                        writer = csv.writer(output)
                        writer.writerow(columns)
                        writer.writerows(cursor.fetchall())

                        if applicant_tool.args.output:
                            print(f"✅ Exported to {applicant_tool.args.output.name}")
                        return

                    rows = cursor.fetchmany(11)
                    if not rows:
                        print("No results found.")
                        return

                    table = PrettyTable()
                    table.field_names = columns
                    for row in rows[:10]:
                        table.add_row(row)

                    print(table)
                    if len(rows) > 10:
                        print(
                            "⚠️  Warning: Showing only first 10 results. Use --csv to see all."
                        )
                else:
                    applicant_tool.db.commit()
                    print(f"OK. Rows affected: {cursor.rowcount}")

            except sqlite3.Error as ex:
                print(f"❌ SQL Error: {ex}")
                return 1

        if initial_sql := applicant_tool.args.sql:
            return execute(initial_sql)

        if not sys.stdin.isatty():
            return execute(sys.stdin.read())

        print("SQL Console (Enter to exit, Ctrl+C to clear line)")
        try:
            while True:
                try:
                    user_input = input("sql> ").strip()
                    if not user_input or user_input in ("exit", "quite", r"\q", "q"):
                        break
                    execute(user_input)
                    print()
                except KeyboardInterrupt:
                    print("^C")
                    continue
        except EOFError:
            print()
