from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from ..main import BaseNamespace, BaseOperation
from ..utils.browser_cookies import find_hh_browser_profiles
from ..utils.ui import console, info, make_table, section, warn

if TYPE_CHECKING:
    from ..main import HHApplicantTool


class Namespace(BaseNamespace):
    pass


class Operation(BaseOperation):
    """Список профилей hh.ru (локальных и из браузеров)"""

    __aliases__: list[str] = ["profiles", "ls-profiles"]
    __category__: str = "Авторизация"

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, tool: HHApplicantTool) -> int | None:
        from ..main import DEFAULT_CONFIG_DIR

        base_dir = Path(DEFAULT_CONFIG_DIR)

        section("Локальные профили")
        local_profiles = _find_local_profiles(base_dir)
        if local_profiles:
            t = make_table("Профиль", "Путь", "Токен", "Последний вход")
            for name, pinfo in local_profiles:
                token_cell = (
                    "[hh.ok]✓ активен[/]" if pinfo["has_token"]
                    else "[hh.muted]✗ нет[/]"
                )
                t.add_row(
                    f"[hh.profile]{name}[/]",
                    f"[hh.dim]{pinfo['path']}[/]",
                    token_cell,
                    pinfo["last_login"] or "[hh.muted]—[/]",
                )
            console.print(t)
        else:
            info("нет локальных профилей")

        section("Браузерные сессии")
        browser_profiles = find_hh_browser_profiles()
        if browser_profiles:
            t2 = make_table("Браузер", "Пользователь", "Куки")
            for p in browser_profiles:
                t2.add_row(
                    f"[bold]{p.browser}[/]",
                    f"[hh.id]{p.username}[/]",
                    str(p.cookie_count),
                )
            console.print(t2)
            console.print(
                "\n[hh.muted]Использовать:[/] "
                "[bold]hh-applicant-tool authorize --from-browser[/]\n"
            )
        else:
            info("активных сессий hh.ru в браузерах не найдено")
            try:
                import rookiepy  # noqa: F401
            except ImportError:
                warn(
                    "rookiepy не установлен — "
                    "запустите [bold]pip install rookiepy[/] для поиска браузерных сессий"
                )

        return 0


def _find_local_profiles(
    base_dir,
) -> list[tuple[str, dict]]:
    """Находит все локальные профили в директории конфига."""
    import json

    result = []
    if not base_dir.exists():
        return result

    # Кандидаты: сам корень (дефолтный профиль) + все подпапки
    candidates: list[tuple[str, Path]] = []
    has_root = (base_dir / "config.json").exists() or (base_dir / "data").exists()
    if has_root:
        candidates.append(("default", base_dir))
    for entry in sorted(base_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        # Не дублируем: если корень уже добавлен как "default", пропускаем подпапку default
        display_name = entry.name
        if has_root and entry.name == "default":
            display_name = "default (sub)"
        candidates.append((display_name, entry))

    for name, entry in candidates:
        config_file = entry / "config.json"
        data_file = entry / "data"
        if not config_file.exists() and not data_file.exists():
            continue

        has_token = False
        last_login = None

        if config_file.exists():
            try:
                cfg = json.loads(config_file.read_text())
                has_token = bool(cfg.get("token", {}).get("access_token"))
            except Exception:
                pass

        if data_file.exists():
            try:
                import sqlite3

                conn = sqlite3.connect(data_file)
                row = conn.execute(
                    "SELECT value FROM settings WHERE key='auth.last_login'"
                ).fetchone()
                if row:
                    last_login = row[0]
                conn.close()
            except Exception:
                pass

        result.append((name, {
            "path": entry,
            "has_token": has_token,
            "last_login": last_login,
        }))

    return result
