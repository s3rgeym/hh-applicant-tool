"""
Централизованный UI-слой на базе Rich.
Всё, что связано с красивым выводом — здесь.
"""
from __future__ import annotations

from typing import Any

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# ─── Цветовая схема ───────────────────────────────────────────────────────────

HH_THEME = Theme({
    "hh.brand":   "bold #FF3D00",      # оранжево-красный, как у hh.ru
    "hh.accent":  "#FF6B35",           # светлее
    "hh.muted":   "#6C7A89",           # серый
    "hh.dim":     "dim #888888",
    "hh.ok":      "bold #2ECC71",      # зелёный
    "hh.warn":    "bold #F39C12",      # оранжевый
    "hh.err":     "bold #E74C3C",      # красный
    "hh.head":    "bold white",
    "hh.profile": "bold #5DADE2",      # голубой
    "hh.id":      "#AEB6BF",
    "hh.label":   "bold #FF6B35",      # акцент для заголовков
    "hh.section": "bold #FF3D00",      # заголовки секций (как у Claude)
    "hh.border":  "#FF3D00",
})

console = Console(theme=HH_THEME)
err_console = Console(theme=HH_THEME, stderr=True)

# ─── Пиксельный персонаж ──────────────────────────────────────────────────────
# Пиксельный "охотник за головами" — стилизованный skull в духе claude code

_PIXEL_ART = (
    "  [#FF3D00]▄▄███▄▄[/]\n"
    " [#FF3D00]█[/][#FF6B35]░░░░░░░[/][#FF3D00]█[/]\n"
    " [#FF3D00]█[/][#FFFFFF] ●   ● [/][#FF3D00]█[/]\n"
    " [#FF3D00]█[/][#FF6B35]  ▄▄▄  [/][#FF3D00]█[/]\n"
    " [#FF3D00]█[/][#FF6B35] ░█░█░ [/][#FF3D00]█[/]\n"
    "  [#FF3D00]▀███████▀[/]\n"
    " [#FF6B35]▄█[/][#FF3D00]█████[/][#FF6B35]█▄[/]\n"
    " [#FF6B35]█ █ █ █ █[/]"
)

# ─── Баннер в стиле Claude Code ───────────────────────────────────────────────

def print_banner(
    username: str | None = None,
    last_login: str | None = None,
    profile: str | None = None,
    recent_activity: list[str] | None = None,
    version: str = "1.8.0",
) -> None:
    """
    Двухколоночный баннер в стиле Claude Code.
    Левая колонка: персонаж + приветствие + мета.
    Правая колонка: советы и последняя активность.
    """

    # ── Левая колонка ──────────────────────────────────────────────────────
    greeting = Text()
    if username:
        greeting.append("С возвращением, ", style="bold white")
        greeting.append(f"{username}!", style="bold #FF6B35")
    else:
        greeting.append("hh-applicant-tool", style="bold #FF6B35")

    pixel = Text.from_markup(_PIXEL_ART)

    meta = Text(justify="center")
    meta.append(f"v{version}", style="#FF6B35")
    if profile and profile != "default":
        meta.append(f"  ·  профиль: ", style="hh.muted")
        meta.append(profile, style="hh.profile")
    if last_login:
        meta.append(f"\nпоследний вход: {last_login}", style="hh.muted")

    left = Text(justify="center")
    left.append("\n")
    left.append_text(greeting)
    left.append("\n\n")
    left.append_text(pixel)
    left.append("\n\n")
    left.append_text(meta)
    left.append("\n")

    # ── Правая колонка ─────────────────────────────────────────────────────
    right = Text()

    # Советы
    right.append("Быстрый старт\n", style="hh.section")
    tips = [
        ("authorize", "войти в аккаунт hh.ru"),
        ("list-profiles", "профили и браузерные сессии"),
        ("apply-vacancies --search python", "откликнуться на вакансии"),
        ("run-all apply-vacancies", "запуск для всех аккаунтов"),
    ]
    for cmd, desc in tips:
        right.append(f"  {cmd}\n", style="bold white")
        right.append(f"    {desc}\n", style="hh.muted")

    right.append("\n")

    # Последняя активность
    right.append("Последняя активность\n", style="hh.section")
    if recent_activity:
        for line in recent_activity:
            right.append(f"  {line}\n", style="hh.muted")
    else:
        right.append("  Нет недавней активности\n", style="hh.muted")

    # ── Layout ─────────────────────────────────────────────────────────────
    ver_str = _get_version_str(version)

    left_panel = Panel(left, border_style="#FF3D00", padding=(0, 2))
    right_panel = Panel(right, border_style="#FF3D00", padding=(0, 2))

    # Table.grid — единственный надёжный способ горизонтального layout в Rich
    grid = Table.grid(expand=True, padding=0)
    grid.add_column(ratio=5, vertical="middle")
    grid.add_column(ratio=7, vertical="top")
    grid.add_row(left_panel, right_panel)

    console.print(
        Panel(
            grid,
            title=f"[hh.brand]hh-applicant-tool[/] [hh.muted]{ver_str}[/]",
            title_align="left",
            border_style="hh.border",
            padding=(0, 0),
        )
    )


def _get_version_str(fallback: str = "1.8.0") -> str:
    try:
        from importlib.metadata import version
        return f"v{version('hh-applicant-tool')}"
    except Exception:
        return f"v{fallback}"


def print_banner_from_tool(tool: Any) -> None:
    """
    Загружает контекст из tool и рисует баннер.
    Используется в main.py при запуске без команды.
    """
    username = None
    last_login = None
    recent_activity: list[str] = []
    profile = getattr(tool.args, "profile_id", None) or "default"

    try:
        s = tool.storage.settings
        username = s.get_value("user.full_name") or s.get_value("auth.username")
        last_login = s.get_value("auth.last_login")
        if last_login and "T" in last_login:
            last_login = last_login.replace("T", " ").split(".")[0]
    except Exception:
        pass

    try:
        import sqlite3
        conn = sqlite3.connect(tool.db_path)
        rows = conn.execute(
            """
            SELECT v.name, n.created_at
            FROM negotiations n
            JOIN vacancies v ON v.id = n.vacancy_id
            ORDER BY n.created_at DESC LIMIT 4
            """
        ).fetchall()
        conn.close()
        for vname, created_at in rows:
            date = (created_at or "")[:10]
            short = vname[:35] + ("…" if len(vname) > 35 else "")
            recent_activity.append(f"{date}  {short}")
    except Exception:
        pass

    try:
        ver = _get_version_str()
    except Exception:
        ver = "1.8.0"

    print_banner(
        username=username,
        last_login=last_login,
        profile=profile,
        recent_activity=recent_activity or None,
        version=ver.lstrip("v"),
    )


# ─── Таблицы ──────────────────────────────────────────────────────────────────

def make_table(*headers: str, title: str | None = None) -> Table:
    t = Table(
        box=box.ROUNDED,
        title=title,
        title_style="hh.label",
        header_style="hh.head",
        border_style="#444444",
        show_lines=False,
        pad_edge=True,
    )
    for h in headers:
        t.add_column(h)
    return t


# ─── Примитивы ────────────────────────────────────────────────────────────────

def panel(content: Any, title: str = "", style: str = "#444444") -> Panel:
    return Panel(content, title=title, title_align="left", border_style=style)


def section(title: str) -> None:
    console.print(Rule(title, style="hh.border"))


def ok(msg: str) -> None:
    console.print(f"[hh.ok]✓[/] {msg}")


def warn(msg: str) -> None:
    console.print(f"[hh.warn]⚠[/] {msg}")


def err(msg: str) -> None:
    err_console.print(f"[hh.err]✗[/] {msg}")


def info(msg: str) -> None:
    console.print(f"[hh.muted]{msg}[/]")


def bold(msg: str) -> None:
    console.print(f"[bold]{msg}[/]")


# ─── Прогресс ─────────────────────────────────────────────────────────────────

def make_progress():
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )
    return Progress(
        SpinnerColumn(style="hh.brand"),
        TextColumn("[bold]{task.description}"),
        BarColumn(bar_width=30, style="hh.brand", complete_style="hh.accent"),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
