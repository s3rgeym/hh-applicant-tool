# Этот код сгенерирован хуИИ, поэтому он может содержать баги
"""Вывод таблиц в терминал: рамки, перенос текста, обрезка, авто-ширина колонок."""

from __future__ import annotations

import os
import shutil
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


# --------------------------------------------------------------------------- #
# Рамки
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BorderStyle:
    """Символы рамки. Можно передать свой экземпляр: Table(rows, style=BorderStyle(...))."""

    top_left: str
    top_mid: str
    top_right: str
    mid_left: str
    mid_mid: str
    mid_right: str
    bottom_left: str
    bottom_mid: str
    bottom_right: str
    vertical: str
    horizontal: str


STYLES = {
    "light": BorderStyle("┌", "┬", "┐", "├", "┼", "┤", "└", "┴", "┘", "│", "─"),
    "rounded": BorderStyle(
        "╭", "┬", "╮", "├", "┼", "┤", "╰", "┴", "╯", "│", "─"
    ),
    "heavy": BorderStyle("┏", "┳", "┓", "┣", "╋", "┫", "┗", "┻", "┛", "┃", "━"),
    "double": BorderStyle(
        "╔", "╦", "╗", "╠", "╬", "╣", "╚", "╩", "╝", "║", "═"
    ),
    "ascii": BorderStyle("+", "+", "+", "+", "+", "+", "+", "+", "+", "|", "-"),
}


# --------------------------------------------------------------------------- #
# Текст ячеек
# --------------------------------------------------------------------------- #
def _cell_text(value: Any) -> str:
    """Значение -> строка для ячейки.

    None даёт пустую ячейку. Табуляции заменяем пробелами, хвостовые пробелы убираем.
    """
    return "" if value is None else str(value).expandtabs(4).rstrip()


def _truncate(value: str, limit: int | None) -> str:
    """Обрезает текст до limit символов, последний символ заменяется на «…»."""
    if limit is not None and len(value) > limit:
        return value[: limit - 1].rstrip() + "…"
    return value


def _wrap(value: str, width: int) -> list[str]:
    """Разбивает текст на строки не длиннее width.

    Явные переводы строк сохраняются, каждый абзац переносится отдельно.
    Слишком длинные слова режутся, чтобы не выходить за рамку.
    У пустой ячейки одна пустая строка, чтобы у неё была высота.
    """
    lines: list[str] = []
    for paragraph in value.splitlines() or [""]:
        lines += textwrap.wrap(
            paragraph,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
        ) or [""]
    return lines


# --------------------------------------------------------------------------- #
# Раскладка ширины колонок
# --------------------------------------------------------------------------- #
def _distribute_width(content_widths: list[int], available: int) -> list[int]:
    """Распределяет ширину между колонками без лишнего растягивания.

    content_widths -- необходимая ширина каждой колонки;
    available      -- суммарная ширина колонок без рамок.

    Если всё помещается, колонки занимают ровно столько места, сколько нужно.
    Если места не хватает, оно распределяется между колонками равномерно.
    Колонки, достигшие необходимой ширины, больше не получают дополнительное
    место. Освободившееся пространство перераспределяется между остальными.
    Минимальная ширина колонки -- 1 символ.
    """
    if not content_widths:
        return []

    if sum(content_widths) <= available:
        return content_widths.copy()

    widths = [1] * len(content_widths)
    remaining = available - len(widths)

    if remaining <= 0:
        return widths

    pending = [
        i for i, content_width in enumerate(content_widths) if content_width > 1
    ]

    while remaining > 0 and pending:
        share, extra = divmod(remaining, len(pending))

        if share == 0:
            for i in pending[:extra]:
                widths[i] += 1
            break

        allocated = 0
        next_pending = []

        for position, i in enumerate(pending):
            capacity = content_widths[i] - widths[i]
            target = share + (position < extra)
            increment = min(capacity, target)

            widths[i] += increment
            allocated += increment

            if widths[i] < content_widths[i]:
                next_pending.append(i)

        remaining -= allocated
        pending = next_pending

    return widths


# --------------------------------------------------------------------------- #
# Таблица
# --------------------------------------------------------------------------- #
class Table:
    """Таблица для вывода в терминале.

    rows     -- список словарей или список списков/кортежей.
    headers  -- заголовки. Для словарей по умолчанию берутся из ключей первого
                словаря (headers задаёт набор и порядок ключей). Для списков без
                headers строка заголовков не выводится.
    style    -- имя стиля из STYLES или свой BorderStyle (по умолчанию «rounded»).
    truncate -- макс. длина текста в ячейке: число для всех колонок или список по
                колонкам (None -- без ограничения). Текст сначала обрезается до
                этой длины, потом раскладывается по колонкам.

    Ширина колонок рассчитывается по содержимому. Если таблица не помещается
    в ширину терминала (80, если её не удалось узнать), колонки сужаются,
    а текст переносится на следующую строку ячейки. Если колонок так много,
    что не помещаются даже рамки и по одному символу на колонку, таблица
    выйдет за пределы терминала.
    """

    def __init__(
        self,
        rows: Sequence[Mapping | Sequence],
        headers: Sequence[Any] | None = None,
        *,
        style: str | BorderStyle = "rounded",
        truncate: int | Sequence[int | None] | None = None,
    ):
        self.rows = list(rows)
        self.headers = list(headers) if headers is not None else None
        self.style = STYLES[style] if isinstance(style, str) else style
        self.truncate = truncate

    def _normalize(self) -> tuple[list[str] | None, list[list[str]]]:
        """Приводит данные к виду (заголовки или None, строки из строк-ячеек)."""
        if len({isinstance(row, Mapping) for row in self.rows}) > 1:
            raise TypeError("Нельзя смешивать словари и последовательности")

        if self.rows and isinstance(self.rows[0], Mapping):
            # Словари: колонки -- это заголовки или ключи первой строки.
            headers = (
                self.headers if self.headers is not None else list(self.rows[0])
            )
            rows = [[row.get(key) for key in headers] for row in self.rows]
        else:
            # Списки: число колонок -- по заголовкам, иначе по самой длинной строке.
            headers = self.headers
            count = (
                len(headers)
                if headers is not None
                else max(map(len, self.rows), default=0)
            )
            # Лишние значения отбрасываем, недостающие дополняем пустыми ячейками.
            rows = [
                list(row[:count]) + [None] * (count - len(row))
                for row in self.rows
            ]

        return (
            None if headers is None else [_cell_text(h) for h in headers],
            [[_cell_text(value) for value in row] for row in rows],
        )

    def _limits(self, count: int) -> list[int | None]:
        """Лимиты длины текста для каждой из count колонок."""
        if self.truncate is None or isinstance(self.truncate, int):
            limits = [self.truncate] * count
        else:
            # Список короче числа колонок дополняем «без ограничения».
            limits = (list(self.truncate) + [None] * count)[:count]

        if any(limit is not None and limit < 1 for limit in limits):
            raise ValueError("truncate должен быть положительным")

        return limits

    def render(self) -> str:
        headers, rows = self._normalize()
        count = (
            len(headers)
            if headers is not None
            else (len(rows[0]) if rows else 0)
        )

        if count == 0:
            return ""

        # 1. Обрезаем текст по truncate.
        all_rows = ([headers] if headers is not None else []) + rows
        limits = self._limits(count)
        all_rows = [
            [_truncate(value, limit) for value, limit in zip(row, limits)]
            for row in all_rows
        ]

        # 2. Ширина каждой колонки по самой длинной строке содержимого.
        content_widths = [
            max(
                [1]
                + [
                    len(part)
                    for row in all_rows
                    for part in row[i].splitlines()
                ],
            )
            for i in range(count)
        ]

        # 3. Вычитаем рамки и пробелы вокруг содержимого ячеек.
        terminal = shutil.get_terminal_size((80, 24)).columns
        available = max(count, terminal - (count * 3 + 1))
        widths = _distribute_width(content_widths, available)

        s = self.style

        def border(left: str, middle: str, right: str) -> str:
            """Горизонтальная линия: ширина колонки + два пробела отступа."""
            return (
                left
                + middle.join(s.horizontal * (width + 2) for width in widths)
                + right
            )

        def render_row(row: list[str]) -> list[str]:
            """Одна логическая строка таблицы -> одна или несколько строк вывода."""
            cells = [_wrap(value, width) for value, width in zip(row, widths)]
            height = max(map(len, cells))

            return [
                s.vertical
                + s.vertical.join(
                    f" {(cell[n] if n < len(cell) else '').ljust(width)} "
                    for cell, width in zip(cells, widths)
                )
                + s.vertical
                for n in range(height)
            ]

        # 4. Верхняя рамка, строки с разделителями и нижняя рамка.
        output = [border(s.top_left, s.top_mid, s.top_right)]

        for index, row in enumerate(all_rows):
            output += render_row(row)

            if index < len(all_rows) - 1:
                output.append(border(s.mid_left, s.mid_mid, s.mid_right))

        output.append(border(s.bottom_left, s.bottom_mid, s.bottom_right))
        return "\n".join(output)

    def print(self) -> None:
        print(self.render())


def print_table(
    rows: Sequence[Mapping | Sequence],
    *args: Any,
    **kwargs: Any,
) -> None:
    """Короткая обёртка: print_table(rows, headers, style='double', truncate=20)."""
    Table(rows, *args, **kwargs).print()


# --------------------------------------------------------------------------- #
# Примеры: python table_min.py
# --------------------------------------------------------------------------- #
def print_example(
    title: str,
    columns: int,
    rows,
    headers=None,
    **kwargs,
) -> None:
    """Печатает таблицу так, будто ширина терминала равна columns."""
    os.environ["COLUMNS"] = str(columns)
    print(f"\n=== {title} (терминал {columns}) ===")
    Table(rows, headers, **kwargs).print()


if __name__ == "__main__":
    text = "Длинный комментарий, который переносится при необходимости"
    people = [
        {"id": 1, "name": "Алиса", "comment": "Коротко"},
        {"id": 2, "name": "Боб", "comment": text},
    ]

    print_example("Помещается: колонки по содержимому", 100, people)
    print_example(
        "Не влезает: длинная колонка сужается, текст переносится",
        40,
        people,
        style="double",
    )
    print_example(
        "truncate, \\n, tab, None, числа",
        60,
        [("а\nб", "x\ty", None, 1.5, text)],
        ["з", "y", "z", "n", "t"],
        truncate=[None, None, None, None, 20],
    )
    print_example(
        "Списки без заголовков",
        30,
        [(1, "a"), (22, "bb", "лишнее")],
    )
    print_example(
        "Пустая таблица с заголовками",
        30,
        [],
        ["A", "B"],
    )
    print_example(
        "Слишком много колонок",
        120,
        [tuple(range(50))],
        [f"c{i}" for i in range(50)],
    )
