# Этот модуль можно использовать как образец для других
from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from ..api import datatypes
from ..main import BaseNamespace, BaseOperation
from ..utils.ui import console, make_table, section

if TYPE_CHECKING:
    from ..main import HHApplicantTool


logger = logging.getLogger(__package__)


class Namespace(BaseNamespace):
    pass


def fmt_plus(n: int) -> str:
    assert n >= 0
    return f"+{n}" if n else "0"


class Operation(BaseOperation):
    """Выведет текущего пользователя"""

    # Это алиасы команды
    __aliases__: list[str] = ["id"]
    __category__: str = "Авторизация"

    def setup_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def run(self, tool: HHApplicantTool) -> None:
        api_client = tool.api_client
        result: datatypes.User = api_client.get("me")
        if result.get('auth_type') != 'applicant':
            logger.warning("Вы вошли не как соискатель! Попробуйте авторизоваться вручную!!!")
        full_name = " ".join(
            filter(
                None,
                [
                    result.get("last_name"),
                    result.get("first_name"),
                    result.get("middle_name"),
                ],
            )
        ) or 'Анонимный аккаунт'
        with tool.storage.settings as s:
            s.set_value("user.full_name", full_name)
            s.set_value("user.email", result.get("email"))
            s.set_value("user.phone", result.get("phone"))
        counters = result.get("counters", {})
        t = make_table("Поле", "Значение", title="Профиль")
        t.add_row("[hh.muted]ID[/]",        f"[hh.id]{result['id']}[/]")
        t.add_row("[hh.muted]Имя[/]",       f"[bold]{full_name}[/]")
        if result.get("email"):
            t.add_row("[hh.muted]Email[/]", result["email"])
        if result.get("phone"):
            t.add_row("[hh.muted]Телефон[/]", result["phone"])
        t.add_row(
            "[hh.muted]Резюме[/]",
            f"[hh.label]{counters.get('resumes_count', 0)}[/]",
        )
        t.add_row(
            "[hh.muted]Новые просмотры[/]",
            f"[hh.ok]{fmt_plus(counters.get('new_resume_views', 0))}[/]",
        )
        t.add_row(
            "[hh.muted]Непрочитанных[/]",
            f"[hh.warn]{fmt_plus(counters.get('unread_negotiations', 0))}[/]",
        )
        console.print(t)
