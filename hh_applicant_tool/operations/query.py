from __future__ import annotations

import argparse
import logging
import sqlite3
import sys

from prettytable import PrettyTable

from ..main import BaseNamespace, BaseOperation, HHApplicantTool

# Пытаемся импортировать readline для поддержки стрелок и истории сессии
try:
    import readline
except ImportError:
    readline = None


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Выполняет SQL-запрос. Поддерживает историю текущей сессии."""

    __aliases__: list[str] = ["sql"]

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("sql", nargs="?", help="SQL запрос для выполнения")

    def run(self, applicant_tool: HHApplicantTool) -> None:
        def execute_and_print(sql_query: str) -> None:
            try:
                cursor = applicant_tool.db.cursor()
                cursor.execute(sql_query)

                # Если запрос возвращает данные (SELECT)
                if cursor.description:
                    columns = [d[0] for d in cursor.description]
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
                        print("⚠️  Warning: Showing only first 10 results.")
                else:
                    # Для INSERT/UPDATE/DELETE
                    applicant_tool.db.commit()
                    print(f"OK. Rows affected: {cursor.rowcount}")

            except sqlite3.Error as ex:
                print(f"❌ SQL Error: {ex}")

        # 1. Если запрос передан в аргументах командной строки
        if initial_sql := applicant_tool.args.sql:
            return execute_and_print(initial_sql)

        # 2. Интерактивный режим
        if not sys.stdout.isatty():
            return

        # Включаем базовую поддержку Tab и истории сессии, если библиотека доступна
        if readline:
            readline.parse_and_bind("tab: complete")

        print("SQL Console (Enter to exit, Ctrl+C to clear line)")

        try:
            while True:
                try:
                    user_input = input("sql> ").strip()

                    # Выход по пустому вводу
                    if not user_input:
                        break

                    execute_and_print(user_input)
                    print()
                except KeyboardInterrupt:
                    # По нажатию Ctrl+C просто очищаем текущую строку
                    print("^C")
                    continue
        except EOFError:
            # Выход по Ctrl+D
            print()
